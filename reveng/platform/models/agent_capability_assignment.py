"""Agents-owned persisted capability assignment relationship."""
from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass
class AgentCapabilityAssignmentRecord:
    id: str
    agent_id: str
    capability_id: str
    assignment_state: str
    scope: str
    assigned_at: str
    revoked_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> "AgentCapabilityAssignmentRecord":
        keys = row.keys() if hasattr(row, "keys") else []
        return cls(
            id=row["id"],
            agent_id=row["agent_id"],
            capability_id=row["capability_id"],
            assignment_state=row["assignment_state"],
            scope=row["scope"] if "scope" in keys else "local",
            assigned_at=row["assigned_at"],
            revoked_at=row["revoked_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @property
    def is_granted(self) -> bool:
        return self.assignment_state == "granted"


__all__ = ["AgentCapabilityAssignmentRecord"]
