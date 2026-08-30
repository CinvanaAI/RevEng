"""Stored Agent Environment background asset rows."""
from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass
class AgentEnvironmentAssetRecord:
    id: str
    environment_id: str
    skin_id: str
    asset_scope: str
    owner_agent_id: str | None
    display_name: str
    original_filename: str
    stored_filename: str
    storage_path: str
    source_kind: str
    source_ref: str | None
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> "AgentEnvironmentAssetRecord":
        return cls(
            id=str(row["id"]),
            environment_id=str(row["environment_id"]),
            skin_id=str(row["skin_id"]),
            asset_scope=str(row["asset_scope"]),
            owner_agent_id=(str(row["owner_agent_id"]) if row["owner_agent_id"] is not None else None),
            display_name=str(row["display_name"]),
            original_filename=str(row["original_filename"]),
            stored_filename=str(row["stored_filename"]),
            storage_path=str(row["storage_path"]),
            source_kind=str(row["source_kind"]),
            source_ref=(str(row["source_ref"]) if row["source_ref"] is not None else None),
            is_active=bool(row["is_active"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


__all__ = ["AgentEnvironmentAssetRecord"]
