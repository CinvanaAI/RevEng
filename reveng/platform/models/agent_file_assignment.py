"""Agents-owned persisted file visibility assignment relationship."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Row


@dataclass
class AgentFileAssignmentRecord:
    id: str
    agent_id: str
    absolute_path: str
    root_path: str
    relative_path: str
    visibility_state: str
    global_tool_eligible: bool
    entry_kind: str          # "file" | "folder"
    assigned_at: str
    revoked_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> "AgentFileAssignmentRecord":
        keys = row.keys()
        return cls(
            id=row["id"],
            agent_id=row["agent_id"],
            absolute_path=row["absolute_path"],
            root_path=row["root_path"],
            relative_path=row["relative_path"],
            visibility_state=row["visibility_state"],
            global_tool_eligible=bool(row["global_tool_eligible"]),
            entry_kind=row["entry_kind"] if "entry_kind" in keys else "file",
            assigned_at=row["assigned_at"],
            revoked_at=row["revoked_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @property
    def is_visible(self) -> bool:
        return self.visibility_state == "granted"

    @property
    def is_folder(self) -> bool:
        return self.entry_kind == "folder"

    @property
    def exists_on_disk(self) -> bool:
        return Path(self.absolute_path).exists()


__all__ = ["AgentFileAssignmentRecord"]
