"""Project supplied location catalogue connected to the persistent script runtime."""
import math
from .model import NotFound
from .scheduler import Scheduler
from .scripts import ScriptDefinition, ScriptResult, Scripts, Transition
from .store import identifier


def location_catalog(value):
    if not isinstance(value, dict) or not isinstance(value.get("locations"), list) or len(value["locations"]) > 512:
        raise ValueError("Location catalogue must contain at most 512 locations")
    seen = set()
    for item in value["locations"]:
        identifier(item["id"])
        identifier("location:" + item["id"])
        if item["id"] in seen:
            raise ValueError("Duplicate location")
        seen.add(item["id"])
        for key in ("x", "z", "radius"):
            if type(item[key]) not in (int, float) or not math.isfinite(item[key]):
                raise ValueError("Location coordinates and radius must be finite numbers")
        if not 0 < item["radius"] <= 65535 or max(abs(item["x"]), abs(item["z"])) > 65535:
            raise ValueError("Location is outside the supported world")
    return value["locations"]


def configure_locations(store, scheduler, scripts, hub):
    def update(context):
        count = context.payload.get("players", 0)
        if type(count) is not int or count < 0:
            raise ValueError("Player count must be a nonnegative integer")
        return ScriptResult({**context.data, "players": count})
    scripts.register_action("platform.presence_update", update)
    scripts.register_definition(ScriptDefinition("platform.location_presence", 1, "inactive", tuple(
        Transition(source, event, target, action="platform.presence_update")
        for source in ("inactive", "active")
        for event, target in (("entered", "active"), ("left", "inactive")))))


def seed_locations(application, catalog):
    locations = location_catalog(catalog)
    with application.open_store() as store:
        scheduler = Scheduler(store, "platform.location_setup")
        scripts = Scripts(store, scheduler)
        configure_locations(store, scheduler, scripts, None)
        for world in application.worlds:
            for item in locations:
                key = "location:" + item["id"]
                try:
                    prior = store.get_entity(world, key)
                except NotFound:
                    scripts.create(world, key, "platform.location_presence", 1,
                        data={"location": dict(item), "players": 0})
                else:
                    if prior.kind != Scripts.KIND or prior.state.get("definition") != "platform.location_presence":
                        raise ValueError("Existing location identity belongs to another entity")
                    if prior.state["data"].get("location") != item:
                        state = {**prior.state, "data": {**prior.state["data"], "location": dict(item)}}
                        store.update_entity(world, key, prior.revision, state)
