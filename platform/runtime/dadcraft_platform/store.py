"""SQLite state and durable event claims, independent of any running engine."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Callable, Iterator
import uuid

from .agent_schema import AGENT_SCHEMA, AGENT_RECOVERY_SCHEMA

from .model import (
    Claim, Clock, Conflict, Effects, Entity, Event, EventSpec, LeaseLost,
    NotFound, Retired, SchemaError, StaleRevision,
)

APPLICATION_ID = 0x44435031
SCHEMA_VERSION = 3
MAX_INT = 2**63 - 1
MAX_JSON_BYTES = 65536
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")

_SCHEMA = (
    "CREATE TABLE worlds (world_id TEXT PRIMARY KEY)",
    """CREATE TABLE clocks (
        world_id TEXT NOT NULL, clock_id TEXT NOT NULL,
        time_ms INTEGER NOT NULL CHECK(time_ms >= 0), paused INTEGER NOT NULL CHECK(paused IN (0,1)),
        PRIMARY KEY(world_id,clock_id), FOREIGN KEY(world_id) REFERENCES worlds(world_id))""",
    """CREATE TABLE regions (
        world_id TEXT NOT NULL, region_id TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)),
        PRIMARY KEY(world_id,region_id), FOREIGN KEY(world_id) REFERENCES worlds(world_id))""",
    """CREATE TABLE entities (
        world_id TEXT NOT NULL, entity_id TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1), region_id TEXT,
        retired INTEGER NOT NULL DEFAULT 0 CHECK(retired IN (0,1)),
        PRIMARY KEY(world_id,entity_id), FOREIGN KEY(world_id) REFERENCES worlds(world_id),
        FOREIGN KEY(world_id,region_id) REFERENCES regions(world_id,region_id))""",
    """CREATE TABLE events (
        world_id TEXT NOT NULL, event_id TEXT NOT NULL, clock_id TEXT NOT NULL,
        handler TEXT NOT NULL, due_ms INTEGER NOT NULL CHECK(due_ms >= 0),
        payload TEXT NOT NULL, target_id TEXT, region_id TEXT, interval_ms INTEGER,
        catch_up TEXT NOT NULL, definition TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','leased','complete','cancelled','failed')),
        attempts INTEGER NOT NULL DEFAULT 0, available_ms INTEGER NOT NULL DEFAULT 0,
        lease_token TEXT, worker_id TEXT, lease_until_ms INTEGER,
        claimed_count INTEGER, claimed_clock_ms INTEGER, last_error TEXT,
        PRIMARY KEY(world_id,event_id),
        FOREIGN KEY(world_id,clock_id) REFERENCES clocks(world_id,clock_id),
        FOREIGN KEY(world_id,target_id) REFERENCES entities(world_id,entity_id),
        FOREIGN KEY(world_id,region_id) REFERENCES regions(world_id,region_id))""",
    "CREATE INDEX events_due ON events(world_id,clock_id,status,due_ms,event_id)",
    "CREATE INDEX events_target ON events(world_id,target_id,status)",
)


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("IDs must be 1..128 ASCII letters, digits or _.:-, starting with a letter or digit")
    return value


def integer(value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_INT:
        raise ValueError(f"Expected an integer in [{minimum}, {MAX_INT}]")
    return value


def _json_object(value: Any) -> str:
    if not isinstance(value, dict):
        raise ValueError("State and payload must be JSON objects")

    def check(v: Any, depth: int) -> None:
        if depth > 32:
            raise ValueError("JSON nesting exceeds 32 levels")
        if isinstance(v, dict):
            if any(not isinstance(k, str) for k in v):
                raise ValueError("JSON object keys must be strings")
            for item in v.values():
                check(item, depth + 1)
        elif isinstance(v, list):
            for item in v:
                check(item, depth + 1)
        elif v is not None and type(v) not in {str, int, float, bool}:
            raise ValueError("Only JSON values are supported")

    check(value, 0)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("JSON record exceeds 64 KiB")
    return encoded


def _entity(row: sqlite3.Row) -> Entity:
    return Entity(row["world_id"], row["entity_id"], row["kind"], json.loads(row["state"]),
                  row["revision"], row["region_id"], bool(row["retired"]))


def _event(row: sqlite3.Row) -> Event:
    return Event(*(row[k] for k in (
        "world_id", "event_id", "clock_id", "handler", "due_ms", "status", "attempts", "last_error")))


class Store:
    """Use one instance per thread; separate connections coordinate via SQLite.

    Each mutation is an IMMEDIATE transaction. This database does not transact
    atomically with a game engine's world database or external side effects.
    """

    def __init__(self, path: str | Path, *, wall_time_ms: Callable[[], int] | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._wall_time_ms = wall_time_ms or (lambda: time.time_ns() // 1_000_000)
        self._db = sqlite3.connect(self.path, isolation_level=None, timeout=1)
        self._db.row_factory = sqlite3.Row
        try:
            app = self._db.execute("PRAGMA application_id").fetchone()[0]
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            occupied = self._db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            if app != APPLICATION_ID and (app != 0 or version != 0 or occupied):
                raise SchemaError("Refusing an unrelated SQLite database")
            if app == APPLICATION_ID and version not in (1, 2, SCHEMA_VERSION):
                raise SchemaError(f"Unsupported platform schema version: {version}")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA synchronous=FULL")
            if app == 0:
                with self._transaction():
                    # Recheck inside the write transaction for concurrent initialization.
                    if self._db.execute("PRAGMA application_id").fetchone()[0] == 0:
                        if self._db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
                            raise SchemaError("Database became occupied during initialization")
                        for statement in _SCHEMA + AGENT_SCHEMA + AGENT_RECOVERY_SCHEMA:
                            self._db.execute(statement)
                        self._db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                        self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    elif (self._db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                          or self._db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION):
                        raise SchemaError("Database identity changed during initialization")
            elif version in (1, 2):
                with self._transaction():
                    current = self._db.execute("PRAGMA user_version").fetchone()[0]
                    if current == 1:
                        for statement in AGENT_SCHEMA:
                            self._db.execute(statement)
                    if current in (1, 2):
                        for statement in AGENT_RECOVERY_SCHEMA:
                            self._db.execute(statement)
                        self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    elif current != SCHEMA_VERSION:
                        raise SchemaError("Database version changed during migration")
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def _require(self, table: str, world: str, field: str | None = None, value: str | None = None) -> sqlite3.Row:
        # table and field are internal constants, never supplied by callers.
        sql = f"SELECT * FROM {table} WHERE world_id=?"
        args = [world]
        if field:
            sql += f" AND {field}=?"
            args.append(value)
        row = self._db.execute(sql, args).fetchone()
        if row is None:
            raise NotFound(f"{table}: {world}/{value or ''}")
        return row

    def create_world(self, world_id: str) -> None:
        world_id = identifier(world_id)
        with self._transaction():
            self._db.execute("INSERT OR IGNORE INTO worlds VALUES (?)", (world_id,))

    def create_clock(self, world_id: str, clock_id: str, *, time_ms: int = 0) -> Clock:
        identifier(world_id), identifier(clock_id), integer(time_ms)
        with self._transaction():
            self._require("worlds", world_id)
            try:
                self._db.execute("INSERT INTO clocks VALUES (?,?,?,0)", (world_id, clock_id, time_ms))
            except sqlite3.IntegrityError as exc:
                raise Conflict("Clock already exists; its time was preserved") from exc
        return self.get_clock(world_id, clock_id)

    def get_clock(self, world_id: str, clock_id: str) -> Clock:
        row = self._require("clocks", identifier(world_id), "clock_id", identifier(clock_id))
        return Clock(world_id, clock_id, row["time_ms"], bool(row["paused"]))

    def advance_clock(self, world_id: str, clock_id: str, delta_ms: int) -> Clock:
        identifier(world_id), identifier(clock_id), integer(delta_ms)
        with self._transaction():
            row = self._require("clocks", world_id, "clock_id", clock_id)
            if not row["paused"]:
                new_time = integer(row["time_ms"] + delta_ms)
                self._db.execute("UPDATE clocks SET time_ms=? WHERE world_id=? AND clock_id=?",
                                 (new_time, world_id, clock_id))
        return self.get_clock(world_id, clock_id)

    def pause_clock(self, world_id: str, clock_id: str, paused: bool) -> Clock:
        identifier(world_id), identifier(clock_id)
        if type(paused) is not bool:
            raise ValueError("paused must be boolean")
        with self._transaction():
            self._require("clocks", world_id, "clock_id", clock_id)
            self._db.execute("UPDATE clocks SET paused=? WHERE world_id=? AND clock_id=?",
                             (int(paused), world_id, clock_id))
        return self.get_clock(world_id, clock_id)

    def create_region(self, world_id: str, region_id: str, *, active: bool = False) -> None:
        identifier(world_id), identifier(region_id)
        if type(active) is not bool:
            raise ValueError("active must be boolean")
        with self._transaction():
            self._require("worlds", world_id)
            try:
                self._db.execute("INSERT INTO regions VALUES (?,?,?)", (world_id, region_id, int(active)))
            except sqlite3.IntegrityError as exc:
                raise Conflict("Region already exists") from exc

    def set_region_active(self, world_id: str, region_id: str, active: bool) -> None:
        identifier(world_id), identifier(region_id)
        if type(active) is not bool:
            raise ValueError("active must be boolean")
        with self._transaction():
            self._require("regions", world_id, "region_id", region_id)
            self._db.execute("UPDATE regions SET active=? WHERE world_id=? AND region_id=?",
                             (int(active), world_id, region_id))

    def create_entity(self, world_id: str, entity_id: str, kind: str, state: dict[str, Any],
                      *, region_id: str | None = None) -> Entity:
        identifier(world_id), identifier(entity_id), identifier(kind)
        encoded = _json_object(state)
        if region_id is not None:
            identifier(region_id)
        with self._transaction():
            self._require("worlds", world_id)
            if region_id is not None:
                self._require("regions", world_id, "region_id", region_id)
            try:
                self._db.execute("INSERT INTO entities VALUES (?,?,?,?,1,?,0)",
                                 (world_id, entity_id, kind, encoded, region_id))
            except sqlite3.IntegrityError as exc:
                raise Conflict("Entity ID already exists and cannot be reused") from exc
        return self.get_entity(world_id, entity_id)

    def get_entity(self, world_id: str, entity_id: str) -> Entity:
        return _entity(self._require("entities", identifier(world_id), "entity_id", identifier(entity_id)))

    def _update_entity(self, world_id: str, entity_id: str, revision: int, state: dict[str, Any]) -> None:
        identifier(entity_id), integer(revision, minimum=1)
        encoded = _json_object(state)
        row = self._require("entities", world_id, "entity_id", entity_id)
        if row["retired"]:
            raise Retired(entity_id)
        if row["revision"] != revision:
            raise StaleRevision(entity_id)
        integer(revision + 1)
        self._db.execute("UPDATE entities SET state=?,revision=revision+1 WHERE world_id=? AND entity_id=?",
                         (encoded, world_id, entity_id))

    def update_entity(self, world_id: str, entity_id: str, expected_revision: int, state: dict[str, Any]) -> Entity:
        identifier(world_id)
        with self._transaction():
            self._update_entity(world_id, entity_id, expected_revision, state)
        return self.get_entity(world_id, entity_id)

    def move_entity(self, world_id: str, entity_id: str, expected_revision: int,
                    region_id: str | None) -> Entity:
        identifier(world_id), identifier(entity_id), integer(expected_revision, minimum=1)
        if region_id is not None:
            identifier(region_id)
        with self._transaction():
            row = self._require("entities", world_id, "entity_id", entity_id)
            if row["retired"]:
                raise Retired(entity_id)
            if row["revision"] != expected_revision:
                raise StaleRevision(entity_id)
            integer(expected_revision + 1)
            if region_id is not None:
                self._require("regions", world_id, "region_id", region_id)
            self._db.execute("UPDATE entities SET region_id=?,revision=revision+1 WHERE world_id=? AND entity_id=?",
                             (region_id, world_id, entity_id))
        return self.get_entity(world_id, entity_id)

    def retire_entity(self, world_id: str, entity_id: str, expected_revision: int) -> Entity:
        identifier(world_id), identifier(entity_id), integer(expected_revision, minimum=1)
        with self._transaction():
            row = self._require("entities", world_id, "entity_id", entity_id)
            if row["revision"] != expected_revision:
                raise StaleRevision(entity_id)
            if not row["retired"]:
                integer(expected_revision + 1)
                self._db.execute("UPDATE entities SET retired=1,revision=revision+1 WHERE world_id=? AND entity_id=?",
                                 (world_id, entity_id))
                self._db.execute("""UPDATE events SET status='cancelled',lease_token=NULL
                    WHERE world_id=? AND target_id=? AND status IN ('pending','leased')""", (world_id, entity_id))
                self._db.execute("""UPDATE agent_controls SET generation=generation+1,controller_id=NULL,
                    token=NULL,expires_ms=0 WHERE world_id=? AND actor_id=?""", (world_id, entity_id))
                self._db.execute("UPDATE agents SET active=0 WHERE world_id=? AND actor_id=?", (world_id, entity_id))
                self._db.execute("""UPDATE agent_actions SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'unknown' END,
                    result=? WHERE world_id=? AND actor_id=? AND status IN ('queued','dispatched')""",
                    (_json_object({"success": False, "error_code": "ACTOR_RETIRED"}), world_id, entity_id))
        return self.get_entity(world_id, entity_id)

    def _schedule(self, world_id: str, spec: EventSpec) -> Event:
        if not isinstance(spec, EventSpec):
            raise ValueError("Expected EventSpec")
        identifier(spec.event_id), identifier(spec.clock_id), identifier(spec.handler), integer(spec.due_ms)
        payload = _json_object(spec.payload)
        if spec.interval_ms is not None:
            integer(spec.interval_ms, minimum=1)
        if not isinstance(spec.catch_up, str) or spec.catch_up not in {"coalesce", "replay"}:
            raise ValueError("catch_up must be coalesce or replay")
        if spec.target_id is not None:
            identifier(spec.target_id)
        if spec.region_id is not None:
            identifier(spec.region_id)
        definition = _json_object(asdict(spec))
        prior = self._db.execute("SELECT * FROM events WHERE world_id=? AND event_id=?",
                                 (world_id, spec.event_id)).fetchone()
        if prior is not None:
            if prior["definition"] != definition:
                raise Conflict("Event ID has a different immutable definition")
            return _event(prior)
        self._require("clocks", world_id, "clock_id", spec.clock_id)
        if spec.target_id is not None:
            target = self._require("entities", world_id, "entity_id", spec.target_id)
            if target["retired"]:
                raise Retired(spec.target_id)
        if spec.region_id is not None:
            self._require("regions", world_id, "region_id", spec.region_id)
        self._db.execute("""INSERT INTO events
            (world_id,event_id,clock_id,handler,due_ms,payload,target_id,region_id,interval_ms,catch_up,definition,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending')""", (
            world_id, spec.event_id, spec.clock_id, spec.handler, spec.due_ms, payload,
            spec.target_id, spec.region_id, spec.interval_ms, spec.catch_up, definition))
        return self.get_event(world_id, spec.event_id)

    def schedule(self, world_id: str, spec: EventSpec) -> Event:
        identifier(world_id)
        with self._transaction():
            return self._schedule(world_id, spec)

    def get_event(self, world_id: str, event_id: str) -> Event:
        return _event(self._require("events", identifier(world_id), "event_id", identifier(event_id)))

    def cancel_event(self, world_id: str, event_id: str) -> Event:
        identifier(world_id), identifier(event_id)
        with self._transaction():
            self._require("events", world_id, "event_id", event_id)
            self._db.execute("""UPDATE events SET status='cancelled',lease_token=NULL
                WHERE world_id=? AND event_id=? AND status IN ('pending','leased','failed')""", (world_id, event_id))
        return self.get_event(world_id, event_id)

    def retry_event(self, world_id: str, event_id: str) -> Event:
        identifier(world_id), identifier(event_id)
        with self._transaction():
            row = self._require("events", world_id, "event_id", event_id)
            if row["status"] != "failed":
                raise Conflict("Only failed events can be explicitly retried")
            if row["target_id"] is not None:
                if self._require("entities", world_id, "entity_id", row["target_id"])["retired"]:
                    raise Retired(row["target_id"])
            self._db.execute("UPDATE events SET status='pending',available_ms=0 WHERE world_id=? AND event_id=?",
                             (world_id, event_id))
        return self.get_event(world_id, event_id)

    def claim_next(self, world_id: str, clock_id: str, worker_id: str, *, lease_ms: int = 30000) -> Claim | None:
        identifier(world_id), identifier(clock_id), identifier(worker_id), integer(lease_ms, minimum=1)
        with self._transaction():
            clock = self._require("clocks", world_id, "clock_id", clock_id)
            if clock["paused"]:
                return None
            now = integer(self._wall_time_ms())
            lease_until = integer(now + lease_ms)
            row = self._db.execute("""SELECT e.* FROM events e
                LEFT JOIN entities t ON t.world_id=e.world_id AND t.entity_id=e.target_id
                WHERE e.world_id=? AND e.clock_id=? AND e.status IN ('pending','leased')
                AND e.due_ms<=? AND e.available_ms<=?
                AND (e.status='pending' OR e.lease_until_ms<=?)
                AND (e.target_id IS NULL OR t.retired=0)
                AND (COALESCE(e.region_id,t.region_id) IS NULL OR EXISTS (
                    SELECT 1 FROM regions r WHERE r.world_id=e.world_id
                    AND r.region_id=COALESCE(e.region_id,t.region_id) AND r.active=1))
                ORDER BY e.due_ms,e.event_id LIMIT 1""", (world_id, clock_id, clock["time_ms"], now, now)).fetchone()
            if row is None:
                return None
            occurrences = 1
            if row["interval_ms"] is not None and row["catch_up"] == "coalesce":
                occurrences += (clock["time_ms"] - row["due_ms"]) // row["interval_ms"]
            token = uuid.uuid4().hex
            attempt = integer(row["attempts"] + 1)
            self._db.execute("""UPDATE events SET status='leased',lease_token=?,worker_id=?,lease_until_ms=?,
                claimed_count=?,claimed_clock_ms=?,attempts=? WHERE world_id=? AND event_id=?""", (
                token, worker_id, lease_until, occurrences, clock["time_ms"], attempt, world_id, row["event_id"]))
            target = self.get_entity(world_id, row["target_id"]) if row["target_id"] is not None else None
            return Claim(world_id, row["event_id"], row["handler"], json.loads(row["payload"]),
                         row["due_ms"], clock["time_ms"], occurrences, attempt, target, worker_id, token)

    def _leased(self, claim: Claim) -> sqlite3.Row:
        row = self._require("events", claim.world_id, "event_id", claim.event_id)
        if (row["status"] != "leased" or row["lease_token"] != claim.lease_token
                or row["worker_id"] != claim.worker_id or row["lease_until_ms"] <= integer(self._wall_time_ms())):
            raise LeaseLost(claim.event_id)
        return row

    def complete(self, claim: Claim, effects: Effects = Effects()) -> Event:
        if not isinstance(effects, Effects) or len(effects.updates) + len(effects.events) > 128:
            raise ValueError("Expected Effects with at most 128 entries")
        with self._transaction():
            row = self._leased(claim)
            if self._require("clocks", claim.world_id, "clock_id", row["clock_id"])["paused"]:
                raise Conflict("Clock was paused during execution")
            region_id = row["region_id"]
            if region_id is None and row["target_id"] is not None:
                region_id = self._require("entities", claim.world_id, "entity_id", row["target_id"])["region_id"]
            if region_id is not None and not self._require("regions", claim.world_id, "region_id", region_id)["active"]:
                raise Conflict("Region was deactivated during execution")
            for update in effects.updates:
                self._update_entity(claim.world_id, update.entity_id, update.expected_revision, update.state)
            for event in effects.events:
                self._schedule(claim.world_id, event)
            next_due = row["due_ms"]
            status = "complete"
            if row["interval_ms"] is not None:
                next_due = integer(next_due + row["interval_ms"] * row["claimed_count"])
                status = "pending"
            self._db.execute("""UPDATE events SET status=?,due_ms=?,lease_token=NULL,worker_id=NULL,
                lease_until_ms=NULL,claimed_count=NULL,claimed_clock_ms=NULL,available_ms=0,last_error=NULL
                WHERE world_id=? AND event_id=?""", (status, next_due, claim.world_id, claim.event_id))
        return self.get_event(claim.world_id, claim.event_id)

    def fail(self, claim: Claim, error: str, *, retry_after_ms: int | None = None) -> Event:
        if not isinstance(error, str):
            raise ValueError("error must be text")
        if retry_after_ms is not None:
            integer(retry_after_ms)
        with self._transaction():
            self._leased(claim)
            available = 0 if retry_after_ms is None else integer(self._wall_time_ms() + retry_after_ms)
            self._db.execute("""UPDATE events SET status=?,lease_token=NULL,worker_id=NULL,lease_until_ms=NULL,
                claimed_count=NULL,claimed_clock_ms=NULL,available_ms=?,last_error=?
                WHERE world_id=? AND event_id=?""", (
                "failed" if retry_after_ms is None else "pending", available, error[:2048], claim.world_id, claim.event_id))
        return self.get_event(claim.world_id, claim.event_id)
