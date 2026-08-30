from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from sqlite3 import Row
from typing import Any

from reveng.framework.logging import FrameworkLogRecord, FrameworkLogSink
from reveng.storage.db_connection import get_db
from reveng.platform.utils import now_utc

from .system_db import ensure_system_db_ready


@dataclass(slots=True)
class StoredFrameworkLogRecord:
    id: str
    logged_at: str
    origin: str
    stage: str
    event_type: str
    level: str
    status: str
    message: str
    run_id: str | None
    workflow_id: str | None
    capability_id: str | None
    trigger: str | None
    details: dict[str, Any]
    boundary_sensitive: bool
    lawful_framework_behavior: bool
    compensating_for_smeared_responsibility: bool
    architectural_drift_detected: bool

    @classmethod
    def from_row(cls, row: Row) -> "StoredFrameworkLogRecord":
        return cls(
            id=row["id"],
            logged_at=row["logged_at"],
            origin=row["origin"],
            stage=row["stage"],
            event_type=row["event_type"],
            level=row["level"],
            status=row["status"],
            message=row["message"],
            run_id=row["run_id"],
            workflow_id=row["workflow_id"],
            capability_id=row["capability_id"],
            trigger=row["trigger"],
            details=json.loads(row["details"]),
            boundary_sensitive=bool(row["boundary_sensitive"]),
            lawful_framework_behavior=bool(row["lawful_framework_behavior"]),
            compensating_for_smeared_responsibility=bool(
                row["compensating_for_smeared_responsibility"]
            ),
            architectural_drift_detected=bool(row["architectural_drift_detected"]),
        )


def build_framework_log_sink(
    db_path: str | None = None,
) -> FrameworkLogSink:
    ensure_system_db_ready(db_path)

    def _sink(record: FrameworkLogRecord) -> None:
        append_framework_log(record)

    return _sink


def append_framework_log(record: FrameworkLogRecord) -> StoredFrameworkLogRecord:
    log_id = str(uuid.uuid4())
    ts = now_utc()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO framework_logs (
                id,
                logged_at,
                run_id,
                workflow_id,
                capability_id,
                origin,
                stage,
                event_type,
                level,
                status,
                trigger,
                message,
                details,
                boundary_sensitive,
                lawful_framework_behavior,
                compensating_for_smeared_responsibility,
                architectural_drift_detected
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                ts,
                record.run_id,
                record.workflow_id,
                record.capability_id,
                record.origin,
                record.stage,
                record.event_type,
                record.level,
                record.status,
                record.trigger,
                record.message,
                json.dumps(record.details, sort_keys=True),
                int(record.boundary_sensitive),
                int(record.lawful_framework_behavior),
                int(record.compensating_for_smeared_responsibility),
                int(record.architectural_drift_detected),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM framework_logs WHERE id = ?",
            (log_id,),
        ).fetchone()
    return StoredFrameworkLogRecord.from_row(row)


def list_framework_logs_for_run(run_id: str) -> list[StoredFrameworkLogRecord]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM framework_logs
            WHERE run_id = ?
            ORDER BY logged_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
    return [StoredFrameworkLogRecord.from_row(row) for row in rows]


def list_recent_framework_logs(limit: int = 100) -> list[StoredFrameworkLogRecord]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM framework_logs
            ORDER BY logged_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [StoredFrameworkLogRecord.from_row(row) for row in rows]
