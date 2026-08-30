"""Small reusable structures for first-class environment objects."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnvironmentObjectDefinition:
    environment_id: str
    display_name: str
    entry_path: str


@dataclass(frozen=True, slots=True)
class EnvironmentStationDefinition:
    action_id: str
    route_segment: str | None
    display_name: str
    description: str
    supports_draft_scope: bool = False
    navigable: bool = True
