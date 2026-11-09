"""Bounded dispatch of named, trusted handlers. No worker starts implicitly."""

from __future__ import annotations

import math
import time
from typing import Callable

from .model import Claim, Conflict, Effects, LeaseLost, RunReport, StaleRevision
from .store import Store, identifier, integer


class Scheduler:
    def __init__(self, store: Store, worker_id: str):
        self.store = store
        self.worker_id = identifier(worker_id)
        self._handlers: dict[str, Callable[[Claim], Effects | None]] = {}

    def register(self, name: str, handler: Callable[[Claim], Effects | None]) -> None:
        identifier(name)
        if not callable(handler):
            raise ValueError("handler must be callable")
        if name in self._handlers:
            raise Conflict("Handler name already registered")
        self._handlers[name] = handler

    def run_due(self, world_id: str, clock_id: str, *, max_events: int = 16,
                max_time_ms: float = 10, lease_ms: int = 30000) -> RunReport:
        integer(max_events, minimum=1)
        integer(lease_ms, minimum=1)
        if isinstance(max_time_ms, bool) or not isinstance(max_time_ms, (int, float)) or not math.isfinite(max_time_ms) or max_time_ms <= 0:
            raise ValueError("max_time_ms must be positive and finite")
        deadline = time.monotonic() + max_time_ms / 1000
        claimed = completed = failed = conflicts = lease_losses = 0
        while claimed < max_events and time.monotonic() < deadline:
            claim = self.store.claim_next(world_id, clock_id, self.worker_id, lease_ms=lease_ms)
            if claim is None:
                break
            claimed += 1
            try:
                handler = self._handlers.get(claim.handler)
                if handler is None:
                    raise ValueError(f"Unknown handler: {claim.handler}")
                effects = handler(claim)
                self.store.complete(claim, Effects() if effects is None else effects)
                completed += 1
            except LeaseLost:
                lease_losses += 1
            except (StaleRevision, Conflict) as exc:
                # Reread/recompute on a later dispatch, without a hot retry loop.
                try:
                    self.store.fail(claim, f"{type(exc).__name__}: {exc}", retry_after_ms=1000)
                    conflicts += 1
                except LeaseLost:
                    lease_losses += 1
            except Exception as exc:
                try:
                    self.store.fail(claim, f"{type(exc).__name__}: {exc}")
                    failed += 1
                except LeaseLost:
                    lease_losses += 1
        return RunReport(claimed, completed, failed, conflicts, lease_losses)
