"""Platform model for capability comparison evidence records."""
from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Row


@dataclass
class ComparisonEvidenceRecord:
    id: str
    run_id: str
    candidate_function_name: str
    target_capability_id: str
    exact_text_match: bool
    normalized_text_match: bool
    ast_structural_match: bool
    function_name_match: bool
    similarity_score: float
    feature_breakdown: dict
    is_literal_duplicate: bool
    created_at: str

    @classmethod
    def from_row(cls, row: Row) -> "ComparisonEvidenceRecord":
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            candidate_function_name=row["candidate_function_name"],
            target_capability_id=row["target_capability_id"],
            exact_text_match=bool(row["exact_text_match"]),
            normalized_text_match=bool(row["normalized_text_match"]),
            ast_structural_match=bool(row["ast_structural_match"]),
            function_name_match=bool(row["function_name_match"]),
            similarity_score=float(row["similarity_score"]),
            feature_breakdown=json.loads(row["feature_breakdown_json"] or "{}"),
            is_literal_duplicate=bool(row["is_literal_duplicate"]),
            created_at=row["created_at"],
        )


__all__ = ["ComparisonEvidenceRecord"]
