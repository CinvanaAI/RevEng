"""Platform-owned publication candidate records."""
from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Row
from typing import Any


@dataclass
class CapabilityPublicationCandidateRecord:
    id: str
    history_id: str
    draft_id: str
    draft_item_id: str
    capability_id: str
    version: str
    publication_state: str
    executable_ready: bool
    implementation_ref: str | None
    combination_logic_ref: str | None
    snapshot_data: dict[str, Any]
    created_at: str

    @classmethod
    def from_row(cls, row: Row) -> "CapabilityPublicationCandidateRecord":
        return cls(
            id=row["id"],
            history_id=row["history_id"],
            draft_id=row["draft_id"],
            draft_item_id=row["draft_item_id"],
            capability_id=row["capability_id"],
            version=row["version"],
            publication_state=row["publication_state"],
            executable_ready=bool(row["executable_ready"]),
            implementation_ref=row["implementation_ref"],
            combination_logic_ref=row["combination_logic_ref"],
            snapshot_data=json.loads(row["snapshot_json"] or "{}"),
            created_at=row["created_at"],
        )


__all__ = ["CapabilityPublicationCandidateRecord"]
