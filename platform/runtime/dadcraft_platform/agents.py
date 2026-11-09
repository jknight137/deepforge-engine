"""World-independent controller fencing and an engine-neutral action outbox."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import sqlite3
from typing import Any
import uuid

from .model import Conflict, EventSpec, LeaseLost, NotFound, PlatformError, Retired, StaleRevision
from .store import Store, _json_object, identifier, integer


def _wire_integer(value: Any, minimum: int = 0) -> int:
    integer(value, minimum=minimum)
    if value > 2**53 - 1:
        raise ValueError("Protocol counter exceeds Lua/JSON's exact integer range")
    return value


class Unavailable(PlatformError):
    """The engine or actor has no current observation."""


class UnsupportedCapability(PlatformError):
    """The attached adapter does not advertise the requested operation."""


@dataclass(frozen=True)
class Control:
    world_id: str
    actor_id: str
    controller_id: str
    generation: int
    token: str
    expires_ms: int


class AgentHub:
    """Trusted local API. HTTP authentication is supplied by the bridge layer.

    Engine outcomes are durable receipts, not a distributed transaction with
    an engine database. An interrupted dispatched action becomes unknown and
    is never automatically repeated across an engine boot.
    """

    def __init__(self, store: Store, *, engine_timeout_ms: int = 10000):
        self.store = store
        self.db = store._db
        self.timeout = integer(engine_timeout_ms, minimum=1)

    def add_world(self, world_id: str) -> None:
        self.store.create_world(world_id)
        try:
            self.store.get_clock(world_id, "simulation")
        except NotFound:
            try:
                self.store.create_clock(world_id, "simulation")
            except Conflict:
                pass

    def _now(self) -> int:
        return integer(self.store._wall_time_ms())

    def _agent(self, world: str, actor: str):
        return self.store._require("agents", identifier(world), "actor_id", identifier(actor))

    def _fresh(self, world: str, actor: str):
        row = self._agent(world, actor)
        engine = self.store._require("agent_engines", world)
        if not row["active"] or self._now() - engine["seen_ms"] > self.timeout:
            raise Unavailable("Actor is inactive or engine heartbeat is stale")
        if self.store.get_entity(world, actor).retired:
            raise Retired(actor)
        return row

    def _lease_duration(self, agent, lease_ms):
        integer(lease_ms, minimum=1000)
        poll_ms = json.loads(agent["observation"]).get("poll_interval_ms", 200)
        minimum = max(1000, 2 * poll_ms + 200)
        if not minimum <= lease_ms <= 120000:
            raise ValueError(f"Control lease must be {minimum}..120000 ms for this engine")

    def _control(self, control: Control, *, allow_expired: bool = False):
        if not isinstance(control, Control):
            raise ValueError("Expected Control")
        identifier(control.controller_id), identifier(control.token)
        _wire_integer(control.generation, 1), _wire_integer(control.expires_ms)
        row = self.store._require("agent_controls", identifier(control.world_id), "actor_id", identifier(control.actor_id))
        if (row["token"] != control.token or row["generation"] != control.generation
                or row["controller_id"] != control.controller_id
                or (not allow_expired and row["expires_ms"] <= self._now())):
            raise LeaseLost("Actor control was expired, released or handed over")
        return row

    @staticmethod
    def _public_action(row) -> dict[str, Any]:
        return {k: (json.loads(row[k]) if k in ("args", "result") and row[k] is not None else row[k])
                for k in ("world_id", "action_id", "actor_id", "controller_id", "generation",
                          "sequence", "operation", "args", "status", "result")}

    def _fence(self, world: str, actor: str) -> None:
        _wire_integer(self.store._require("agent_controls", world, "actor_id", actor)["generation"] + 1)
        self.db.execute("""UPDATE agent_controls SET generation=generation+1,controller_id=NULL,
            token=NULL,expires_ms=0 WHERE world_id=? AND actor_id=?""", (world, actor))
        self.db.execute("""UPDATE agent_actions SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'unknown' END,
            result=? WHERE world_id=? AND actor_id=? AND status IN ('queued','dispatched')""",
            (_json_object({"success": False, "error_code": "CONTROL_INTERRUPTED"}), world, actor))

    def acquire(self, world: str, actor: str, controller: str, *, lease_ms: int = 30000) -> Control:
        identifier(controller)
        with self.store._transaction():
            self._lease_duration(self._fresh(world, actor), lease_ms)
            row = self.store._require("agent_controls", world, "actor_id", actor)
            if row["token"] and row["expires_ms"] > self._now():
                raise Conflict("Actor already has a controller; renew or explicitly hand over")
            self._fence(world, actor)
            generation = integer(row["generation"] + 1, minimum=1)
            token, expires = uuid.uuid4().hex, integer(self._now() + lease_ms)
            self.db.execute("""UPDATE agent_controls SET controller_id=?,generation=?,token=?,expires_ms=?
                WHERE world_id=? AND actor_id=?""", (controller, generation, token, expires, world, actor))
            return Control(world, actor, controller, generation, token, expires)

    def renew(self, control: Control, *, lease_ms: int = 30000) -> Control:
        with self.store._transaction():
            self._control(control)
            self._lease_duration(self._fresh(control.world_id, control.actor_id), lease_ms)
            expires = integer(self._now() + lease_ms)
            self.db.execute("UPDATE agent_controls SET expires_ms=? WHERE world_id=? AND actor_id=?",
                            (expires, control.world_id, control.actor_id))
            return Control(control.world_id, control.actor_id, control.controller_id,
                           control.generation, control.token, expires)

    def current_control(self, world: str, actor: str, controller: str) -> Control:
        identifier(controller)
        self._fresh(world, actor)
        row = self.store._require("agent_controls", world, "actor_id", actor)
        if row["controller_id"] != controller or not row["token"] or row["expires_ms"] <= self._now():
            raise LeaseLost("Controller does not currently own this actor")
        return Control(world, actor, controller, row["generation"], row["token"], row["expires_ms"])

    def release(self, control: Control) -> None:
        with self.store._transaction():
            self._control(control, allow_expired=True)
            self._fence(control.world_id, control.actor_id)

    def handoff(self, control: Control, next_controller: str, *, lease_ms: int = 30000) -> Control:
        identifier(next_controller)
        with self.store._transaction():
            old = self._control(control)
            self._lease_duration(self._fresh(control.world_id, control.actor_id), lease_ms)
            generation = integer(old["generation"] + 1)
            self._fence(control.world_id, control.actor_id)
            token, expires = uuid.uuid4().hex, integer(self._now() + lease_ms)
            self.db.execute("""UPDATE agent_controls SET controller_id=?,token=?,expires_ms=?
                WHERE world_id=? AND actor_id=?""",
                (next_controller, token, expires, control.world_id, control.actor_id))
            return Control(control.world_id, control.actor_id, next_controller, generation, token, expires)

    def agents(self, world: str) -> list[dict[str, Any]]:
        identifier(world)
        rows = self.db.execute("SELECT actor_id,capabilities,active FROM agents WHERE world_id=? ORDER BY active DESC,actor_id LIMIT 256",
                               (world,)).fetchall()
        return [{"actor_id": r["actor_id"], "capabilities": json.loads(r["capabilities"]), "active": bool(r["active"])} for r in rows]

    def observe(self, world: str, actor: str, *, max_age_ms: int = 5000) -> dict[str, Any]:
        integer(max_age_ms, minimum=1)
        row = self._fresh(world, actor)
        if self._now() - row["observed_ms"] > max_age_ms:
            raise Unavailable("Observation is stale")
        return json.loads(row["observation"])

    def submit(self, control: Control, action_id: str, operation: str, args: dict[str, Any],
               *, expected_observation: dict[str, Any] | None = None) -> dict[str, Any]:
        identifier(action_id), identifier(operation)
        encoded = _json_object(args)
        signature = _json_object({"control": asdict(control), "operation": operation,
                                  "args": args, "expected_observation": expected_observation})
        with self.store._transaction():
            prior = self.db.execute("SELECT * FROM agent_actions WHERE world_id=? AND action_id=?",
                                    (control.world_id, action_id)).fetchone()
            if prior is not None:
                if prior["signature"] != signature:
                    raise Conflict("Action ID has a different immutable request")
                return self._public_action(prior)
            self._control(control)
            agent = self._fresh(control.world_id, control.actor_id)
            if self.store.get_clock(control.world_id, "simulation").paused:
                raise Conflict("Simulation clock is paused")
            if operation not in json.loads(agent["capabilities"]):
                raise UnsupportedCapability(operation)
            if expected_observation is not None and self.observe(control.world_id, control.actor_id)["stamp"] != expected_observation:
                raise StaleRevision("Observation stamp changed")
            sequence = _wire_integer(agent["sequence"] + 1)
            try:
                self.db.execute("""INSERT INTO agent_actions
                    (world_id,action_id,actor_id,controller_id,generation,sequence,operation,args,signature,status)
                    VALUES (?,?,?,?,?,?,?,?,?,'queued')""", (control.world_id, action_id, control.actor_id,
                    control.controller_id, control.generation, sequence, operation, encoded, signature))
            except sqlite3.IntegrityError as exc:
                raise Conflict("Actor already has outstanding work") from exc
            self.db.execute("UPDATE agents SET sequence=? WHERE world_id=? AND actor_id=?",
                            (sequence, control.world_id, control.actor_id))
            return self.result(control.world_id, action_id)

    def result(self, world: str, action_id: str, *, controller_id: str | None = None) -> dict[str, Any]:
        row = self.store._require("agent_actions", identifier(world), "action_id", identifier(action_id))
        if controller_id is not None and row["controller_id"] != controller_id:
            raise LeaseLost("Action belongs to another controller")
        return self._public_action(row)

    def cancel(self, control: Control, action_id: str) -> dict[str, Any]:
        with self.store._transaction():
            self._control(control)
            row = self.store._require("agent_actions", control.world_id, "action_id", identifier(action_id))
            if row["actor_id"] != control.actor_id or row["generation"] != control.generation:
                raise LeaseLost("Action belongs to another control generation")
            self.db.execute("""UPDATE agent_actions SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'unknown' END,
                result=? WHERE world_id=? AND action_id=? AND status IN ('queued','dispatched')""",
                (_json_object({"success": False, "error_code": "CANCEL_REQUESTED"}), control.world_id, action_id))
            return self.result(control.world_id, action_id)

    def memory(self, control: Control) -> dict[str, Any]:
        self._control(control)
        entity = self.store.get_entity(control.world_id, control.actor_id)
        return {"revision": entity.revision, "state": entity.state}

    def update_memory(self, control: Control, expected_revision: int, state: dict[str, Any]) -> dict[str, Any]:
        with self.store._transaction():
            self._control(control)
            self.store._update_entity(control.world_id, control.actor_id, expected_revision, state)
            return self.memory(control)

    def _completion(self, world: str, session: str, value: dict[str, Any]) -> None:
        action_id = identifier(value["action_id"])
        identifier(value["actor_id"]), integer(value["sequence"], minimum=1), integer(value["generation"], minimum=1)
        row = self.store._require("agent_actions", world, "action_id", action_id)
        if (row["actor_id"] != value["actor_id"] or row["sequence"] != value["sequence"]
                or row["generation"] != value["generation"] or row["engine_session"] != session):
            raise Conflict("Engine receipt does not match the dispatched command")
        status = value.get("status", "complete")
        if status not in ("complete", "unknown"):
            raise ValueError("Receipt status must be complete or unknown")
        result = value["result"]
        if not isinstance(result, dict) or type(result.get("success")) is not bool:
            raise ValueError("Engine result requires a boolean success field")
        encoded = _json_object(result)
        if row["status"] == "complete":
            if encoded != row["result"]:
                raise Conflict("Completed action has a different receipt")
            return
        if row["status"] not in ("dispatched", "unknown"):
            raise Conflict("Action was never dispatched")
        self.db.execute("UPDATE agent_actions SET status=?,result=? WHERE world_id=? AND action_id=?",
                        (status, encoded, world, action_id))

    def _reject(self, world, session, frame_id, kind, item_id, code, message):
        self.db.execute("INSERT OR IGNORE INTO agent_rejections VALUES (?,?,?,?,?,?,?,?)",
                        (world, session, frame_id, kind, item_id, code, str(message)[:512], self._now()))

    def _frame_item(self, world, session, frame_id, kind, item, index, function):
        item_id = item.get("action_id" if kind == "completion" else "event_id") if isinstance(item, dict) else None
        if not isinstance(item_id, str) or len(item_id) > 128:
            item_id = f"invalid-{kind}-{index}"
        self.db.execute("SAVEPOINT frame_item")
        try:
            function()
        except (NotFound, Conflict, Retired, ValueError, TypeError, KeyError) as exc:
            self.db.execute("ROLLBACK TO frame_item")
            self.db.execute("RELEASE frame_item")
            self._reject(world, session, frame_id, kind, item_id, type(exc).__name__.upper(), exc)
        else:
            self.db.execute("RELEASE frame_item")

    def rejections(self, world):
        identifier(world)
        return [dict(row) for row in self.db.execute("""SELECT kind,item_id,error_code,message,session_id,frame_id
            FROM agent_rejections WHERE world_id=? ORDER BY created_ms DESC,frame_id DESC LIMIT 64""", (world,))]

    def exchange(self, frame: dict[str, Any]) -> dict[str, Any]:
        world, session = identifier(frame["world_id"]), identifier(frame["session_id"])
        frame_id, delta = _wire_integer(frame["frame_id"], 1), integer(frame["delta_ms"])
        if frame.get("protocol_version") != 1 or type(frame.get("protocol_version")) is not int or delta > 60000:
            raise ValueError("Unsupported protocol or clock delta")
        poll_ms = integer(frame.get("poll_interval_ms", 200), minimum=50)
        if poll_ms > 5000:
            raise ValueError("Engine polling interval exceeds 5000 ms")
        actors, completions = frame.get("actors") or [], frame.get("completions") or []
        signals, regions = frame.get("signals") or [], frame.get("regions") or []
        if any(not isinstance(v, list) for v in (actors, completions, signals, regions)):
            raise ValueError("Frame collections must be arrays")
        if len(actors) > 256 or len(completions) > 64 or len(signals) > 64 or len(regions) > 512:
            raise ValueError("Frame collection limit exceeded")
        actor_ids = [identifier(a["actor_id"]) for a in actors]
        if len(set(actor_ids)) != len(actor_ids):
            raise ValueError("Duplicate actor IDs")
        for actor in actors:
            caps = actor["capabilities"]
            if not isinstance(caps, dict) or len(caps) > 64:
                raise ValueError("Capabilities must be a bounded object")
            for name in caps:
                identifier(name)
            observation = actor.get("observation")
            _json_object(caps), _json_object({} if observation is None else observation)
        encoded_frame = json.dumps(frame, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded_frame) > 1048576:
            raise ValueError("Exchange frame exceeds 1 MiB")
        signature = hashlib.sha256(encoded_frame).hexdigest()
        now = self._now()
        with self.store._transaction():
            self.store._require("worlds", world)
            previous = self.db.execute("SELECT * FROM agent_engines WHERE world_id=?", (world,)).fetchone()
            new_boot = previous is None or previous["session_id"] != session
            if new_boot:
                boot = self.db.execute("SELECT retired FROM agent_boots WHERE world_id=? AND session_id=?", (world, session)).fetchone()
                if boot is not None and boot["retired"]:
                    raise Conflict("Retired engine session cannot return")
                if previous is not None and now - previous["seen_ms"] <= self.timeout:
                    raise Conflict("Another engine session is still live for this world")
                if frame_id != 1:
                    raise Conflict("A new engine session must start at frame 1")
                if previous is not None:
                    self.db.execute("UPDATE agent_boots SET retired=1 WHERE world_id=? AND session_id=?", (world, previous["session_id"]))
                    for row in self.db.execute("SELECT actor_id FROM agents WHERE world_id=?", (world,)).fetchall():
                        self._fence(world, row["actor_id"])
                self.db.execute("INSERT OR IGNORE INTO agent_boots VALUES (?,?,0)", (world, session))
            elif frame_id == previous["frame_id"]:
                if signature != previous["frame_hash"]:
                    raise Conflict("Frame ID was reused with different content")
                self.db.execute("UPDATE agent_engines SET seen_ms=? WHERE world_id=?", (now, world))
                return self._response(world, session, frame_id, actors)
            elif frame_id != previous["frame_id"] + 1:
                raise Conflict("Engine frame sequence is not contiguous")
            # Old-boot completions cannot settle new-boot state.
            for index, completion in enumerate(completions):
                self._frame_item(world, session, frame_id, "completion", completion, index,
                                 lambda item=completion: self._completion(world, session, item))
            missing = [r["actor_id"] for r in self.db.execute("SELECT actor_id FROM agents WHERE world_id=? AND active=1", (world,))
                       if r["actor_id"] not in set(actor_ids)]
            for actor_id in missing:
                self._fence(world, actor_id)
            self.db.execute("UPDATE agents SET active=0 WHERE world_id=?", (world,))
            for actor in actors:
                actor_id = actor["actor_id"]
                entity = self.db.execute("SELECT retired FROM entities WHERE world_id=? AND entity_id=?", (world, actor_id)).fetchone()
                if entity is not None and entity["retired"]:
                    existing_control = self.db.execute("SELECT token FROM agent_controls WHERE world_id=? AND actor_id=?", (world, actor_id)).fetchone()
                    if existing_control and existing_control["token"]:
                        self._fence(world, actor_id)
                    self._reject(world, session, frame_id, "actor", actor_id, "RETIRED", "Actor identity is retired")
                    continue
                self.db.execute("INSERT OR IGNORE INTO entities VALUES (?,?,?,'{}',1,NULL,0)", (world, actor_id, "platform.actor"))
                observation_data = actor.get("observation")
                observation = _json_object({"stamp": {"session_id": session, "frame_id": frame_id}, "poll_interval_ms": poll_ms,
                                            "data": {} if observation_data is None else observation_data})
                self.db.execute("""INSERT INTO agents(world_id,actor_id,capabilities,observation,observed_ms,active)
                    VALUES (?,?,?,?,?,1) ON CONFLICT(world_id,actor_id) DO UPDATE SET
                    capabilities=excluded.capabilities,observation=excluded.observation,observed_ms=excluded.observed_ms,active=1""",
                    (world, actor_id, _json_object(actor["capabilities"]), observation, now))
                self.db.execute("INSERT OR IGNORE INTO agent_controls(world_id,actor_id) VALUES (?,?)", (world, actor_id))
            clock = self.store.get_clock(world, "simulation")
            if not clock.paused:
                _wire_integer(clock.time_ms + delta)
                self.db.execute("UPDATE clocks SET time_ms=time_ms+? WHERE world_id=? AND clock_id='simulation'", (delta, world))
            for region in regions:
                identifier(region["region_id"])
                if type(region["active"]) is not bool:
                    raise ValueError("Region active flag must be boolean")
                self.db.execute("INSERT INTO regions VALUES (?,?,?) ON CONFLICT(world_id,region_id) DO UPDATE SET active=excluded.active",
                                (world, region["region_id"], int(region["active"])))
            def schedule_signal(signal):
                if not isinstance(signal, dict):
                    raise ValueError("Signal must be an object")
                signal_payload = signal.get("payload")
                _json_object({} if signal_payload is None else signal_payload)
                self.store._schedule(world, EventSpec(identifier(signal["event_id"]), "simulation", "platform.script_event",
                    integer(signal["due_ms"]), {"event": identifier(signal["event"]), "data": {} if signal_payload is None else signal_payload},
                    target_id=identifier(signal["instance_id"])))
            for index, signal in enumerate(signals):
                self._frame_item(world, session, frame_id, "signal", signal, index,
                                 lambda item=signal: schedule_signal(item))
            self.db.execute("""INSERT INTO agent_engines VALUES (?,?,?,?,?) ON CONFLICT(world_id) DO UPDATE SET
                session_id=excluded.session_id,frame_id=excluded.frame_id,frame_hash=excluded.frame_hash,seen_ms=excluded.seen_ms""",
                (world, session, frame_id, signature, now))
            return self._response(world, session, frame_id, actors)

    def _response(self, world: str, session: str, frame_id: int, actors: list[dict]) -> dict[str, Any]:
        now = self._now()
        clock = self.store.get_clock(world, "simulation")
        _wire_integer(clock.time_ms)
        grants, commands = [], []
        command_bytes = 0
        for actor_state in actors:
            actor = actor_state["actor_id"]
            entity = self.store.get_entity(world, actor)
            if entity.retired:
                self._reject(world, session, frame_id, "actor", actor, "RETIRED", "Actor identity is retired")
                continue
            row = self.store._require("agent_controls", world, "actor_id", actor)
            remaining = max(0, row["expires_ms"] - now) if row["token"] else 0
            grant = {"actor_id": actor, "generation": row["generation"], "remaining_ms": remaining, "action_id": None}
            grants.append(grant)
            action = self.db.execute("""SELECT * FROM agent_actions WHERE world_id=? AND actor_id=?
                AND status IN ('queued','dispatched')""", (world, actor)).fetchone()
            if action is not None and remaining and not clock.paused and action["generation"] == row["generation"]:
                grant["action_id"] = action["action_id"]
                command = self._public_action(action)
                command.pop("result")
                size = len(json.dumps(command, allow_nan=False).encode())
                if (actor_state.get("running_action_id") == action["action_id"]
                        or len(commands) >= 16 or command_bytes + size > 262144):
                    continue
                self.db.execute("UPDATE agent_actions SET status='dispatched',engine_session=? WHERE world_id=? AND action_id=?",
                                (session, world, action["action_id"]))
                commands.append(command)
                command_bytes += size
        rejected = [dict(row) for row in self.db.execute("""SELECT kind,item_id,error_code,message FROM agent_rejections
            WHERE world_id=? AND session_id=? AND frame_id=? ORDER BY kind,item_id""", (world, session, frame_id))]
        return {"protocol_version": 1, "world_id": world, "session_id": session, "frame_id": frame_id,
                "clock_ms": clock.time_ms, "paused": clock.paused, "grants": grants, "commands": commands,
                "rejections": rejected}
