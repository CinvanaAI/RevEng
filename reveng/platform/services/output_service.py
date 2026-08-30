"""OutputService — record and query run output artifacts."""
from __future__ import annotations

import json
import uuid

from reveng.storage.db_connection import get_db
from reveng.platform.models.output import RunOutputRecord
from reveng.platform.utils import now_utc


class OutputService:
    def record(
        self,
        run_id: str,
        output_key: str,
        output_type: str,
        value: str,
        metadata: dict | None = None,
    ) -> RunOutputRecord:
        output_id = str(uuid.uuid4())
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO run_outputs
                    (id, run_id, output_key, output_type, value, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (output_id, run_id, output_key, output_type, value,
                 json.dumps(metadata or {}), ts),
            )
            conn.commit()
        return RunOutputRecord(
            id=output_id,
            run_id=run_id,
            output_key=output_key,
            output_type=output_type,
            value=value,
            metadata=metadata or {},
            created_at=ts,
        )

    def get_outputs_for_run(self, run_id: str) -> list[RunOutputRecord]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM run_outputs WHERE run_id = ? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
        return [RunOutputRecord.from_row(r) for r in rows]
