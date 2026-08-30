"""Capability Environment station definitions."""
from __future__ import annotations

from urllib.parse import urlencode

from reveng.execution_environment.core import (
    EnvironmentObjectDefinition,
    EnvironmentStationDefinition,
)


CAPABILITY_ENVIRONMENT_OBJECT = EnvironmentObjectDefinition(
    environment_id="capability_environment",
    display_name="Capability Environment",
    entry_path="/capability-environment",
)

CAPABILITY_ENVIRONMENT_STATIONS = (
    EnvironmentStationDefinition(
        action_id="create_draft",
        route_segment="create-draft",
        display_name="Create Draft",
        description="Start a new non-live draft intentionally.",
    ),
    EnvironmentStationDefinition(
        action_id="inventory_wall",
        route_segment="inventory-wall",
        display_name="Inventory Wall",
        description="Inspect live installed capabilities without editing them.",
    ),
    EnvironmentStationDefinition(
        action_id="workbench",
        route_segment="workbench",
        display_name="Workbench",
        description="List and continue current draft work.",
        supports_draft_scope=True,
    ),
    EnvironmentStationDefinition(
        action_id="ledger",
        route_segment="ledger",
        display_name="Ledger",
        description="Inspect saved draft records, revisions, and publication history.",
        supports_draft_scope=True,
    ),
    EnvironmentStationDefinition(
        action_id="dispatch_bench",
        route_segment="dispatch-bench",
        display_name="Dispatch Bench",
        description="Validate, publish, and export from draft state.",
        supports_draft_scope=True,
    ),
    EnvironmentStationDefinition(
        action_id="return",
        route_segment=None,
        display_name="Return",
        description="Leave Capability Environment.",
        navigable=False,
    ),
)

CAPABILITY_ENVIRONMENT_STATION_BY_ACTION = {
    station.action_id: station for station in CAPABILITY_ENVIRONMENT_STATIONS
}
CAPABILITY_ENVIRONMENT_STATION_BY_ROUTE_SEGMENT = {
    station.route_segment: station
    for station in CAPABILITY_ENVIRONMENT_STATIONS
    if station.route_segment is not None
}
CAPABILITY_ENVIRONMENT_STATION_ALIASES = {
    "forge": "create_draft",
    "inventory": "inventory_wall",
    "drafts": "workbench",
    "draft": "workbench",
    "dispatch": "dispatch_bench",
}


def resolve_capability_environment_station_action(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in CAPABILITY_ENVIRONMENT_STATION_BY_ACTION:
        return normalized
    if normalized in CAPABILITY_ENVIRONMENT_STATION_BY_ROUTE_SEGMENT:
        return CAPABILITY_ENVIRONMENT_STATION_BY_ROUTE_SEGMENT[normalized].action_id
    return CAPABILITY_ENVIRONMENT_STATION_ALIASES.get(normalized)


def build_capability_environment_station_href(
    action_id: str,
    *,
    return_to_query: str,
    draft_id: str | None = None,
    selected_draft_id: str | None = None,
    base_path: str = "/capability-environment",
) -> str:
    station = CAPABILITY_ENVIRONMENT_STATION_BY_ACTION[action_id]
    if not station.navigable:
        raise ValueError(f"{action_id!r} is not a navigable station.")

    params: list[tuple[str, str]] = []
    if return_to_query:
        params.append(("return", return_to_query))

    params.append(("station", action_id))
    scoped_draft_id = None
    if action_id in {"ledger", "dispatch_bench"} and draft_id:
        scoped_draft_id = draft_id
    elif action_id in {"ledger", "dispatch_bench"} and selected_draft_id:
        scoped_draft_id = selected_draft_id
    elif action_id == "workbench" and selected_draft_id:
        scoped_draft_id = selected_draft_id
    if scoped_draft_id:
        params.append(("draft", scoped_draft_id))

    query = f"?{urlencode(params)}" if params else ""
    return f"{base_path}{query}"


__all__ = [
    "CAPABILITY_ENVIRONMENT_OBJECT",
    "CAPABILITY_ENVIRONMENT_STATIONS",
    "CAPABILITY_ENVIRONMENT_STATION_BY_ACTION",
    "CAPABILITY_ENVIRONMENT_STATION_BY_ROUTE_SEGMENT",
    "CAPABILITY_ENVIRONMENT_STATION_ALIASES",
    "build_capability_environment_station_href",
    "resolve_capability_environment_station_action",
]
