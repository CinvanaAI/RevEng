"""RunService — lifecycle management for analysis runs."""
from __future__ import annotations

import json

from reveng.storage.db_connection import get_db
from reveng.platform.models.run import AnalysisRunRecord
from reveng.platform.utils import now_utc


class RunNotFoundError(Exception):
    pass


class RunService:
    def create(
        self,
        run_id: str,
        repo_path: str,
        output_dir: str,
        options: dict,
        agent_id: str | None = None,
    ) -> AnalysisRunRecord:
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO analysis_runs
                    (id, status, repo_path, output_dir, options, agent_id,
                     started_at, finished_at, error_message, created_at, updated_at)
                VALUES (?, 'pending', ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
                """,
                (run_id, repo_path, output_dir, json.dumps(options), agent_id, ts, ts),
            )
            conn.commit()
        return self.get_or_raise(run_id)

    def get(self, run_id: str) -> AnalysisRunRecord | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return AnalysisRunRecord.from_row(row) if row else None

    def get_or_raise(self, run_id: str) -> AnalysisRunRecord:
        record = self.get(run_id)
        if record is None:
            raise RunNotFoundError(f"Run not found: {run_id}")
        return record

    def list_runs(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[AnalysisRunRecord]:
        with get_db() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM analysis_runs WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM analysis_runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        return [AnalysisRunRecord.from_row(r) for r in rows]

    def count(self, status: str | None = None) -> int:
        with get_db() as conn:
            if status:
                row = conn.execute(
                    "SELECT COUNT(*) FROM analysis_runs WHERE status = ?", (status,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()
        return row[0]

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def mark_running(self, run_id: str) -> None:
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                "UPDATE analysis_runs SET status='running', started_at=?, updated_at=? WHERE id=?",
                (ts, ts, run_id),
            )
            conn.commit()

    def mark_completed(self, run_id: str) -> None:
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                "UPDATE analysis_runs SET status='completed', finished_at=?, updated_at=? WHERE id=?",
                (ts, ts, run_id),
            )
            conn.commit()

    def mark_failed(self, run_id: str, error: str) -> None:
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                UPDATE analysis_runs
                SET status='failed', finished_at=?, error_message=?, updated_at=?
                WHERE id=?
                """,
                (ts, error, ts, run_id),
            )
            conn.commit()
