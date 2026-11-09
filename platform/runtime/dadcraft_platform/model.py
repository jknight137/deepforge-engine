"""Version-one platform records. No game or engine-specific rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PlatformError(Exception):
    """Base class for explicit platform failures."""


class Conflict(PlatformError):
    """An immutable identity or event definition already exists."""


class NotFound(PlatformError):
    """The requested world, clock, region, entity or event is missing."""


class StaleRevision(PlatformError):
    """Another writer has changed the entity since it was read."""


class LeaseLost(PlatformError):
    """An event execution lease has expired or been replaced."""


class Retired(PlatformError):
    """An entity identity has been permanently retired."""


class SchemaError(PlatformError):
    """The file is not a supported platform database."""


@dataclass(frozen=True)
class Entity:
    world_id: str
    entity_id: str
    kind: str
    state: dict[str, Any]
    revision: int
    region_id: str | None
    retired: bool


@dataclass(frozen=True)
class Clock:
    world_id: str
    clock_id: str
    time_ms: int
    paused: bool


@dataclass(frozen=True)
class EventSpec:
    event_id: str
    clock_id: str
    handler: str
    due_ms: int
    payload: dict[str, Any] = field(default_factory=dict)
    target_id: str | None = None
    region_id: str | None = None
    interval_ms: int | None = None
    catch_up: str = "coalesce"


@dataclass(frozen=True)
class Event:
    world_id: str
    event_id: str
    clock_id: str
    handler: str
    due_ms: int
    status: str
    attempts: int
    last_error: str | None


@dataclass(frozen=True)
class Claim:
    world_id: str
    event_id: str
    handler: str
    payload: dict[str, Any]
    scheduled_ms: int
    clock_ms: int
    occurrences: int
    attempt: int
    target: Entity | None
    worker_id: str
    lease_token: str

    @property
    def lateness_ms(self) -> int:
        return self.clock_ms - self.scheduled_ms


@dataclass(frozen=True)
class StateUpdate:
    entity_id: str
    expected_revision: int
    state: dict[str, Any]


@dataclass(frozen=True)
class Effects:
    """Updates, child events and acknowledgement commit in one transaction."""

    updates: tuple[StateUpdate, ...] = ()
    events: tuple[EventSpec, ...] = ()


@dataclass(frozen=True)
class RunReport:
    claimed: int
    completed: int
    failed: int
    conflicts: int
    lease_losses: int
