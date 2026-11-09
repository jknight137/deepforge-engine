"""Controller SDK for the universal platform service."""

from __future__ import annotations

from dataclasses import asdict
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from pathlib import Path

from .agents import Control
from .store import identifier


class RemoteError(RuntimeError):
    def __init__(self, status: int, value: dict):
        self.status, self.code = status, value.get("error_code", "HTTP_ERROR")
        super().__init__(f"{self.code}: {value.get('message', 'Request failed')}")


class PlatformClient:
    @classmethod
    def from_world(cls, world):
        folder = Path(world).resolve() / ".platform"
        config = json.loads((folder / "client.json").read_text(encoding="utf-8"))
        token = (folder / config["token_file"]).read_text(encoding="utf-8").strip()
        return cls(config["world_id"], token, base_url=config["base_url"])

    def __init__(self, world_id: str, token: str, *, base_url: str = "http://127.0.0.1:8775", timeout: float = 3):
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path not in ("", "/") or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("Platform URL must be an IPv4 loopback HTTP origin")
        if not isinstance(token, str) or len(token) < 24:
            raise ValueError("A controller token of at least 24 characters is required")
        self.world_id, self.token = identifier(world_id), token
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    def _request(self, method: str, route: str, body=None):
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = Request(f"{self.base_url}/v1/worlds/{self.world_id}/{route}", data=data, method=method,
                          headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            with exc:
                raise RemoteError(exc.code, json.load(exc)) from exc

    def agents(self):
        return self._request("GET", "agents")["agents"]

    def entity(self, entity_id: str):
        return self._request("GET", f"entities/{identifier(entity_id)}")

    def rejections(self):
        return self._request("GET", "rejections")["rejections"]

    def observe(self, actor_id: str):
        return self._request("GET", f"agents/{identifier(actor_id)}/observation")

    def acquire(self, actor_id: str, *, lease_ms: int = 30000) -> Control:
        return Control(**self._request("POST", "control/acquire", {"actor_id": identifier(actor_id), "lease_ms": lease_ms}))

    def current_control(self, actor_id: str) -> Control:
        return Control(**self._request("POST", "control/current", {"actor_id": identifier(actor_id)}))

    def renew(self, control: Control, *, lease_ms: int = 30000) -> Control:
        return Control(**self._request("POST", "control/renew", {"control": asdict(control), "lease_ms": lease_ms}))

    def release(self, control: Control):
        return self._request("POST", "control/release", {"control": asdict(control)})

    def handoff(self, control: Control, next_controller: str, *, lease_ms: int = 30000) -> Control:
        return Control(**self._request("POST", "control/handoff", {"control": asdict(control),
                        "next_controller": identifier(next_controller), "lease_ms": lease_ms}))

    def submit(self, control: Control, action_id: str, operation: str, args: dict, *, expected_observation=None):
        return self._request("POST", "actions", {"control": asdict(control), "action_id": identifier(action_id),
                             "operation": identifier(operation), "args": args, "expected_observation": expected_observation})

    def result(self, action_id: str):
        return self._request("GET", f"actions/{identifier(action_id)}")

    def wait_result(self, action_id: str, *, timeout: float = 30):
        deadline = time.monotonic() + timeout
        while True:
            value = self.result(action_id)
            if value["status"] not in ("queued", "dispatched"):
                return value
            if time.monotonic() >= deadline:
                raise TimeoutError("Action outcome is unresolved; retain the same action ID")
            time.sleep(0.05)

    def cancel(self, control: Control, action_id: str):
        return self._request("POST", "actions/cancel", {"control": asdict(control), "action_id": identifier(action_id)})

    def memory(self, control: Control):
        return self._request("POST", "memory/get", {"control": asdict(control)})

    def update_memory(self, control: Control, expected_revision: int, state: dict):
        return self._request("POST", "memory/update", {"control": asdict(control),
                             "expected_revision": expected_revision, "state": state})
