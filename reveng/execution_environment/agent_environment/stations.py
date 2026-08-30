"""Agent Environment station definitions."""
from __future__ import annotations

from urllib.parse import urlencode

from reveng.execution_environment.core import (
    EnvironmentObjectDefinition,
    EnvironmentStationDefinition,
)


AGENT_ENVIRONMENT_OBJECT = EnvironmentObjectDefinition(
    environment_id="agent_environment",
    display_name="Agent Environment",
    entry_path="/agent-environment",
)

AGENT_ENVIRONMENT_STATIONS = (
    EnvironmentStationDefinition(
        action_id="agent_hall",
        route_segment=None,
        display_name="Agent Hall",
        description="Choose an agent bay inside the environment.",
    ),
    EnvironmentStationDefinition(
        action_id="tools_station",
        route_segment="tools",
        display_name="Tools Station",
        description="Grant and revoke installed capability packages for the selected agent.",
    ),
    EnvironmentStationDefinition(
        action_id="keycard_station",
        route_segment="keycard",
        display_name="Keycard Station",
        description="Assign visible files and manage per-file tool permissions for the selected agent.",
    ),
    EnvironmentStationDefinition(
        action_id="return",
        route_segment=None,
        display_name="Return",
        description="Leave Agent Environment.",
        navigable=False,
    ),
)

AGENT_ENVIRONMENT_STATION_BY_ACTION = {
    station.action_id: station for station in AGENT_ENVIRONMENT_STATIONS
}


def build_agent_environment_entry_href(
    *,
    return_to_query: str,
    agent_id: str | None = None,
    base_path: str = "/agent-environment",
) -> str:
    params: list[tuple[str, str]] = []
    if return_to_query:
        params.append(("return", return_to_query))
    if agent_id:
        params.append(("agent", agent_id))
    if not params:
        return base_path
    return f"{base_path}?{urlencode(params)}"


def build_agent_environment_agent_href(
    agent_id: str,
    *,
    return_to_query: str,
    station: str | None = None,
    explorer_root_path: str | None = None,
    explorer_current_path: str | None = None,
) -> str:
    path = f"/agent-environment/agents/{agent_id}"
    if station == "tools_station":
        path = f"{path}/tools"
    elif station == "keycard_station":
        path = f"{path}/keycard"
    params: list[tuple[str, str]] = []
    if return_to_query:
        params.append(("return", return_to_query))
    if explorer_root_path:
        params.append(("root", explorer_root_path))
    if explorer_current_path:
        params.append(("browse", explorer_current_path))
    query = f"?{urlencode(params)}" if params else ""
    return f"{path}{query}"


__all__ = [
    "AGENT_ENVIRONMENT_OBJECT",
    "AGENT_ENVIRONMENT_STATIONS",
    "AGENT_ENVIRONMENT_STATION_BY_ACTION",
    "build_agent_environment_agent_href",
    "build_agent_environment_entry_href",
]
