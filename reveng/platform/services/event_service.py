"""EventService — append-only run event log."""
from __future__ import annotations

import json
import uuid

from reveng.storage.db_connection import get_db
from reveng.platform.models.event import RunEventRecord
from reveng.platform.utils import now_utc


class EventService:
    def append(
        self,
        run_id: str,
        event_type: str,
        payload: dict,
        run_type: str = "analysis",
    ) -> RunEventRecord:
        event_id = str(uuid.uuid4())
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO run_events (id, run_id, run_type, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, run_id, run_type, event_type, json.dumps(payload), ts),
            )
            conn.commit()
        return RunEventRecord(
            id=event_id,
            run_id=run_id,
            run_type=run_type,
            event_type=event_type,
            payload=payload,
            created_at=ts,
        )

    def get_events_for_run(
        self,
        run_id: str,
        since: str | None = None,
    ) -> list[RunEventRecord]:
        """
        Return all events for a run, ordered by created_at ascending.
        If *since* is provided (ISO-8601 timestamp), return only events after that time.
        """
        with get_db() as conn:
            if since:
                rows = conn.execute(
                    """
                    SELECT * FROM run_events
                    WHERE run_id = ? AND created_at > ?
                    ORDER BY created_at ASC
                    """,
                    (run_id, since),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM run_events WHERE run_id = ? ORDER BY created_at ASC",
                    (run_id,),
                ).fetchall()
        return [RunEventRecord.from_row(r) for r in rows]
