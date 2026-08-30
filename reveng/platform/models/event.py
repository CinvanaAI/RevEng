"""RunEventRecord — append-only event log entry."""
from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Row


@dataclass
class RunEventRecord:
    id: str
    run_id: str
    run_type: str    # "analysis" | "agent"
    event_type: str  # "status_change" | "output_ready" | "error" | "info" | "warning"
    payload: dict
    created_at: str

    @classmethod
    def from_row(cls, row: Row) -> RunEventRecord:
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            run_type=row["run_type"],
            event_type=row["event_type"],
            payload=json.loads(row["payload"]),
            created_at=row["created_at"],
        )
