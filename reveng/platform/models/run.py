"""Run records — analysis runs and agent runs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Row


@dataclass
class AnalysisRunRecord:
    id: str
    status: str           # "pending" | "running" | "completed" | "failed"
    repo_path: str
    output_dir: str
    options: dict         # with_ai, layered, ai_limit, etc.
    agent_id: str | None  # None for headless/manual runs
    started_at: str | None
    finished_at: str | None
    error_message: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> AnalysisRunRecord:
        return cls(
            id=row["id"],
            status=row["status"],
            repo_path=row["repo_path"],
            output_dir=row["output_dir"],
            options=json.loads(row["options"]),
            agent_id=row["agent_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class AgentRunRecord:
    id: str
    agent_id: str
    analysis_run_id: str | None
    status: str           # "pending" | "running" | "completed" | "failed"
    input_payload: dict
    output_payload: dict
    error_message: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> AgentRunRecord:
        return cls(
            id=row["id"],
            agent_id=row["agent_id"],
            analysis_run_id=row["analysis_run_id"],
            status=row["status"],
            input_payload=json.loads(row["input_payload"]),
            output_payload=json.loads(row["output_payload"]),
            error_message=row["error_message"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
