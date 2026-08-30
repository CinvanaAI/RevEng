"""Platform service for capability comparison evidence storage."""
from __future__ import annotations

import json
import uuid
from typing import Any

from reveng.storage.db_connection import get_db
from reveng.platform.models.comparison_evidence import ComparisonEvidenceRecord
from reveng.platform.utils import now_utc


class ComparisonEvidenceService:
    """
    Truth owner for deterministic comparison evidence produced by Blacksmith runs.

    Separate from OutputService (run artifacts) and EventService (run lifecycle).
    This is comparison semantics — a distinct concern.
    """

    def record(
        self,
        *,
        run_id: str,
        candidate_function_name: str,
        target_capability_id: str,
        exact_text_match: bool,
        normalized_text_match: bool,
        ast_structural_match: bool,
        function_name_match: bool,
        similarity_score: float,
        feature_breakdown: dict[str, Any],
        is_literal_duplicate: bool,
    ) -> str:
        """Insert one comparison evidence row. Returns the new evidence_id."""
        evidence_id = str(uuid.uuid4())
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO capability_comparison_evidence (
                    id, run_id, candidate_function_name, target_capability_id,
                    exact_text_match, normalized_text_match, ast_structural_match,
                    function_name_match, similarity_score, feature_breakdown_json,
                    is_literal_duplicate, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    run_id,
                    candidate_function_name,
                    target_capability_id,
                    int(exact_text_match),
                    int(normalized_text_match),
                    int(ast_structural_match),
                    int(function_name_match),
                    float(similarity_score),
                    json.dumps(feature_breakdown, sort_keys=True),
                    int(is_literal_duplicate),
                    ts,
                ),
            )
            conn.commit()
        return evidence_id

    def list_for_run(self, run_id: str) -> list[ComparisonEvidenceRecord]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM capability_comparison_evidence
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [ComparisonEvidenceRecord.from_row(row) for row in rows]

    def list_duplicates_for_run(self, run_id: str) -> list[ComparisonEvidenceRecord]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM capability_comparison_evidence
                WHERE run_id = ? AND is_literal_duplicate = 1
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [ComparisonEvidenceRecord.from_row(row) for row in rows]


__all__ = ["ComparisonEvidenceService"]
