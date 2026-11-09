"""Persistent event-driven scripts with registered conditions and actions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from .model import Claim, Conflict, Effects, Entity, Event, EventSpec, StateUpdate
from .scheduler import Scheduler
from .store import Store, identifier, integer


@dataclass(frozen=True)
class Transition:
    source: str
    event: str
    target: str
    condition: str | None = None
    action: str | None = None


@dataclass(frozen=True)
class ScriptDefinition:
    name: str
    version: int
    initial: str
    transitions: tuple[Transition, ...]


@dataclass(frozen=True)
class ScriptContext:
    claim: Claim
    event: str
    payload: dict[str, Any]
    data: dict[str, Any]


@dataclass(frozen=True)
class ScriptResult:
    data: dict[str, Any]
    effects: Effects = Effects()


class Scripts:
    """Definitions are registered code; each instance's state lives in Store.

    Conditions and actions must not perform external side effects. They return
    state/event effects for the scheduler's atomic commit.
    """

    HANDLER = "platform.script_event"
    KIND = "platform.script"

    def __init__(self, store: Store, scheduler: Scheduler):
        if scheduler.store is not store:
            raise ValueError("Scripts and scheduler must share a Store instance")
        self.store = store
        self._definitions: dict[tuple[str, int], ScriptDefinition] = {}
        self._transitions: dict[tuple[str, int], dict[tuple[str, str], Transition]] = {}
        self._conditions: dict[str, Callable[[ScriptContext], bool]] = {}
        self._actions: dict[str, Callable[[ScriptContext], ScriptResult]] = {}
        scheduler.register(self.HANDLER, self._handle)

    def register_definition(self, definition: ScriptDefinition) -> None:
        identifier(definition.name), identifier(definition.initial)
        integer(definition.version, minimum=1)
        keys = set()
        if len(definition.transitions) > 1024:
            raise ValueError("A definition may have at most 1024 transitions")
        for transition in definition.transitions:
            identifier(transition.source), identifier(transition.event), identifier(transition.target)
            if transition.condition is not None:
                identifier(transition.condition)
            if transition.action is not None:
                identifier(transition.action)
            key = (transition.source, transition.event)
            if key in keys:
                raise Conflict("Ambiguous transitions for the same state and event")
            keys.add(key)
        key = (definition.name, definition.version)
        if key in self._definitions:
            raise Conflict("Script definition version already registered")
        stored = deepcopy(definition)
        self._definitions[key] = stored
        self._transitions[key] = {(t.source, t.event): t for t in stored.transitions}

    def register_condition(self, name: str, condition: Callable[[ScriptContext], bool]) -> None:
        identifier(name)
        if not callable(condition):
            raise ValueError("condition must be callable")
        if name in self._conditions:
            raise Conflict("Condition already registered")
        self._conditions[name] = condition

    def register_action(self, name: str, action: Callable[[ScriptContext], ScriptResult]) -> None:
        identifier(name)
        if not callable(action):
            raise ValueError("action must be callable")
        if name in self._actions:
            raise Conflict("Action already registered")
        self._actions[name] = action

    def create(self, world_id: str, instance_id: str, definition: str, version: int,
               *, data: dict[str, Any] | None = None, region_id: str | None = None) -> Entity:
        identifier(definition), integer(version, minimum=1)
        spec = self._definitions.get((definition, version))
        if spec is None:
            raise ValueError("Script definition version is not registered")
        if data is not None and not isinstance(data, dict):
            raise ValueError("Script data must be a JSON object")
        return self.store.create_entity(world_id, instance_id, self.KIND, {
            "definition": definition, "version": version, "node": spec.initial,
            "data": {} if data is None else data,
        }, region_id=region_id)

    def emit(self, world_id: str, instance_id: str, event_id: str, event: str,
             *, clock_id: str, due_ms: int, payload: dict[str, Any] | None = None) -> Event:
        identifier(event)
        entity = self.store.get_entity(world_id, instance_id)
        if entity.kind != self.KIND:
            raise ValueError("Event target is not a platform script")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("Event payload must be a JSON object")
        return self.store.schedule(world_id, EventSpec(
            event_id, clock_id, self.HANDLER, due_ms,
            {"event": event, "data": {} if payload is None else payload}, target_id=instance_id))

    def _handle(self, claim: Claim) -> Effects:
        target = claim.target
        if target is None or target.kind != self.KIND:
            raise ValueError("Script event requires a script instance")
        state = deepcopy(target.state)
        key = (state["definition"], state["version"])
        definition = self._definitions.get(key)
        if definition is None:
            raise ValueError("Stored script definition version is not registered")
        event = identifier(claim.payload["event"])
        transition = self._transitions[key].get((state["node"], event))
        if transition is None:
            return Effects()  # Explicitly ignored in the current state.
        context = ScriptContext(claim, event, deepcopy(claim.payload["data"]), deepcopy(state["data"]))
        if transition.condition is not None:
            condition = self._conditions.get(transition.condition)
            if condition is None:
                raise ValueError("Script condition is not registered")
            allowed = condition(context)
            if type(allowed) is not bool:
                raise ValueError("Script condition must return a boolean")
            if not allowed:
                return Effects()
        result = ScriptResult(deepcopy(state["data"]))
        if transition.action is not None:
            action = self._actions.get(transition.action)
            if action is None:
                raise ValueError("Script action is not registered")
            # A condition must not accidentally pass mutated local data to an action.
            context = ScriptContext(claim, event, deepcopy(claim.payload["data"]), deepcopy(state["data"]))
            result = action(context)
            if not isinstance(result, ScriptResult) or not isinstance(result.data, dict) or not isinstance(result.effects, Effects):
                raise ValueError("Script action must return ScriptResult with object data and Effects")
        if any(update.entity_id == target.entity_id for update in result.effects.updates):
            raise ValueError("Action cannot also update its own script instance")
        updated = {"definition": state["definition"], "version": state["version"],
                   "node": transition.target, "data": result.data}
        return Effects(
            updates=(StateUpdate(target.entity_id, target.revision, updated),) + tuple(result.effects.updates),
            events=tuple(result.effects.events),
        )
