"""Authenticated local HTTP transport for engines and controller projects."""

from __future__ import annotations

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from .agents import AgentHub, Control, Unavailable, UnsupportedCapability
from .model import Conflict, LeaseLost, NotFound, Retired, StaleRevision
from .scheduler import Scheduler
from .scripts import Scripts
from .store import Store, identifier


class Application:
    def __init__(self, database: str | Path, worlds: list[str], engine_token: str,
                 controllers: dict[str, str], *, configure: Callable | None = None,
                 wall_time_ms: Callable[[], int] | None = None):
        self.database = Path(database)
        self.worlds = {identifier(w) for w in worlds}
        self.controllers = {identifier(k): v for k, v in controllers.items()}
        self.engine_token = engine_token
        self.configure = configure
        self.wall_time_ms = wall_time_ms
        tokens = [engine_token, *controllers.values()]
        if not self.worlds or not controllers or any(not isinstance(t, str) or len(t) < 24 for t in tokens):
            raise ValueError("Worlds, controllers and distinct tokens of at least 24 characters are required")
        if len(set(tokens)) != len(tokens):
            raise ValueError("Engine and controller tokens must be distinct")
        with self.open_store() as store:
            for world in self.worlds:
                AgentHub(store).add_world(world)

    def open_store(self) -> Store:
        return Store(self.database, wall_time_ms=self.wall_time_ms)

    def handle(self, method: str, path: str, token: str, body=None) -> tuple[int, dict]:
        try:
            return self._handle(method, path, token, {} if body is None else body)
        except PermissionError:
            return 403, {"error_code": "FORBIDDEN", "message": "Credentials do not authorize this operation"}
        except NotFound as exc:
            return 404, {"error_code": "NOT_FOUND", "message": str(exc)}
        except Unavailable as exc:
            return 503, {"error_code": "UNAVAILABLE", "message": str(exc)}
        except (Conflict, StaleRevision, LeaseLost, Retired) as exc:
            return 409, {"error_code": type(exc).__name__.upper(), "message": str(exc)}
        except UnsupportedCapability as exc:
            return 422, {"error_code": "UNSUPPORTED_CAPABILITY", "message": str(exc)}
        except (ValueError, TypeError, KeyError) as exc:
            return 400, {"error_code": "INVALID_REQUEST", "message": str(exc)}

    def _handle(self, method: str, path: str, token: str, body: dict) -> tuple[int, dict]:
        if not isinstance(body, dict) or not isinstance(token, str):
            raise ValueError("Request must be a JSON object")
        engine = hmac.compare_digest(token, self.engine_token)
        owner = next((name for name, secret in self.controllers.items() if hmac.compare_digest(token, secret)), None)
        if not engine and owner is None:
            raise PermissionError()
        path = urlsplit(path).path
        with self.open_store() as store:
            hub = AgentHub(store)
            if method == "GET" and path == "/health":
                return 200, {"protocol_version": 1, "service": "dadcraft-platform", "worlds": sorted(self.worlds)}
            if path == "/v1/engine/exchange" and method == "POST":
                if not engine or body.get("world_id") not in self.worlds:
                    raise PermissionError()
                watch = body.get("watch_scripts") or []
                if not isinstance(watch, list) or len(watch) > 8:
                    raise ValueError("At most 8 script watches are allowed")
                for name in watch:
                    identifier(name)
                response = hub.exchange(body)
                scheduler = Scheduler(store, "platform.bridge")
                scripts = Scripts(store, scheduler)
                if self.configure is not None:
                    self.configure(store, scheduler, scripts, hub)
                report = scheduler.run_due(body["world_id"], "simulation", max_events=16, max_time_ms=5)
                response["dispatch"] = asdict(report)
                response["scripts"] = []
                for name in watch:
                    try:
                        entity = store.get_entity(body["world_id"], name)
                    except NotFound:
                        continue
                    if entity.kind == Scripts.KIND:
                        response["scripts"].append({"instance_id": name, "revision": entity.revision, "state": entity.state})
                return 200, response
            if owner is None:
                raise PermissionError()
            parts = [unquote(p) for p in path.strip("/").split("/")]
            if len(parts) < 4 or parts[:2] != ["v1", "worlds"]:
                raise NotFound("Route")
            world = identifier(parts[2])
            if world not in self.worlds:
                raise PermissionError()
            route = "/".join(parts[3:])

            def control() -> Control:
                value = Control(**body["control"])
                if value.world_id != world or value.controller_id != owner:
                    raise PermissionError()
                return value

            if method == "GET" and route == "agents":
                return 200, {"agents": hub.agents(world)}
            if method == "GET" and len(parts) == 5 and parts[3] == "entities":
                return 200, asdict(store.get_entity(world, parts[4]))
            if method == "GET" and route == "rejections":
                return 200, {"rejections": hub.rejections(world)}
            if method == "GET" and len(parts) == 6 and parts[3] == "agents" and parts[5] == "observation":
                return 200, hub.observe(world, parts[4])
            if method == "GET" and len(parts) == 5 and parts[3] == "actions":
                return 200, hub.result(world, parts[4], controller_id=owner)
            if method != "POST":
                raise NotFound("Route")
            if route == "control/acquire":
                return 200, asdict(hub.acquire(world, body["actor_id"], owner, lease_ms=body.get("lease_ms", 30000)))
            if route == "control/current":
                return 200, asdict(hub.current_control(world, body["actor_id"], owner))
            if route == "control/renew":
                return 200, asdict(hub.renew(control(), lease_ms=body.get("lease_ms", 30000)))
            if route == "control/release":
                hub.release(control())
                return 200, {"released": True}
            if route == "control/handoff":
                if body["next_controller"] not in self.controllers:
                    raise ValueError("Next controller is not configured")
                return 200, asdict(hub.handoff(control(), body["next_controller"], lease_ms=body.get("lease_ms", 30000)))
            if route == "actions":
                return 202, hub.submit(control(), body["action_id"], body["operation"], body["args"],
                                       expected_observation=body.get("expected_observation"))
            if route == "actions/cancel":
                return 200, hub.cancel(control(), body["action_id"])
            if route == "memory/get":
                return 200, hub.memory(control())
            if route == "memory/update":
                return 200, hub.update_memory(control(), body["expected_revision"], body["state"])
            raise NotFound("Route")


def make_server(application: Application, *, port: int = 8775) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def log_message(self, *_):
            pass

        def do_GET(self):
            self.respond("GET")

        def do_POST(self):
            self.respond("POST")

        def respond(self, method):
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Transfer encoding is unsupported")
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1048576:
                    raise ValueError("Request body limit is 1 MiB")
                body = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON"))) if length else {}
                auth = self.headers.get("Authorization", "")
                token = auth[7:] if auth.startswith("Bearer ") else ""
                status, result = application.handle(method, self.path, token, body)
            except (ValueError, UnicodeError, TimeoutError) as exc:
                status, result = 400, {"error_code": "INVALID_REQUEST", "message": str(exc)}
            except Exception:
                status, result = 500, {"error_code": "INTERNAL_ERROR", "message": "Operation failed; request outcome may be unknown"}
            data = json.dumps(result, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
