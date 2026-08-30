"""Stored per-agent Agent Environment skin/background preferences."""
from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass
class AgentEnvironmentAgentSkinPreferenceRecord:
    id: str
    agent_id: str
    skin_id: str
    background_mode: str
    selected_asset_id: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> "AgentEnvironmentAgentSkinPreferenceRecord":
        return cls(
            id=str(row["id"]),
            agent_id=str(row["agent_id"]),
            skin_id=str(row["skin_id"]),
            background_mode=str(row["background_mode"]),
            selected_asset_id=(
                str(row["selected_asset_id"])
                if row["selected_asset_id"] is not None
                else None
            ),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


__all__ = ["AgentEnvironmentAgentSkinPreferenceRecord"]
