"""RunOutputRecord — captured artifact reference for a completed run."""
from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Row


@dataclass
class RunOutputRecord:
    id: str
    run_id: str
    output_key: str   # e.g. "inventory_path", "file_count"
    output_type: str  # "file_path" | "count" | "inline_json"
    value: str
    metadata: dict
    created_at: str

    @classmethod
    def from_row(cls, row: Row) -> RunOutputRecord:
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            output_key=row["output_key"],
            output_type=row["output_type"],
            value=row["value"],
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
        )
