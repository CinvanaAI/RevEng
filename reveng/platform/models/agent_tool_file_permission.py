"""Agents-owned persisted per-tool file permission relationship."""
from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass
class AgentToolFilePermissionRecord:
    id: str
    agent_id: str
    capability_id: str
    absolute_path: str
    permission_state: str
    source_kind: str
    granted_at: str
    revoked_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> "AgentToolFilePermissionRecord":
        return cls(
            id=row["id"],
            agent_id=row["agent_id"],
            capability_id=row["capability_id"],
            absolute_path=row["absolute_path"],
            permission_state=row["permission_state"],
            source_kind=row["source_kind"],
            granted_at=row["granted_at"],
            revoked_at=row["revoked_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @property
    def is_granted(self) -> bool:
        return self.permission_state == "granted"


__all__ = ["AgentToolFilePermissionRecord"]
