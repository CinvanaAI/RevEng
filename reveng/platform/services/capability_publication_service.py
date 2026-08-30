"""Platform-side publication candidate persistence."""
from __future__ import annotations

import json
import uuid

from reveng.platform.capability_combination_logic import (
    binding_ref_for_combination_logic_kind,
)
from reveng.storage.db_connection import get_db
from reveng.platform.models.capability_publication import CapabilityPublicationCandidateRecord
from reveng.platform.utils import now_utc


class CapabilityPublicationService:
    """
    Persist platform publication candidates.

    Published draft items become durable publication candidates as part of the
    live-install path. This preserves inspectable evidence of the publication
    step even when publish proceeds to replace installed capability truth.
    """

    def record_draft_publication_candidates(
        self,
        *,
        conn,
        draft,
        items,
        history_id: str,
    ) -> dict[str, int]:
        ts = now_utc()
        total = 0
        executable_ready = 0

        for item in items:
            draft_data = dict(item.draft_data)
            implementation_ref = draft_data.get("implementation_ref")
            combination_logic_ref = draft_data.get("combination_logic_ref")
            if not combination_logic_ref and draft_data.get("capability_type") == "composite":
                logic_kind = draft_data.get("combination_logic_kind", "merge")
                combination_logic_ref = binding_ref_for_combination_logic_kind(logic_kind)
            is_executable = bool(implementation_ref or combination_logic_ref)
            capability_id = draft_data.get("capability_id") or item.planned_capability_id
            version = draft_data.get("version") or draft.version
            snapshot = {
                "draft": {
                    "id": draft.id,
                    "name": draft.name,
                    "description": draft.description,
                    "version": draft.version,
                    "lifecycle_state": draft.lifecycle_state,
                },
                "item": {
                    "id": item.id,
                    "planned_capability_id": item.planned_capability_id,
                    "item_state": item.item_state,
                    "draft_data": draft_data,
                },
                "publication_history_id": history_id,
            }
            conn.execute(
                """
                INSERT INTO capability_publication_candidates (
                    id,
                    history_id,
                    draft_id,
                    draft_item_id,
                    capability_id,
                    version,
                    publication_state,
                    executable_ready,
                    implementation_ref,
                    combination_logic_ref,
                    snapshot_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    history_id,
                    draft.id,
                    item.id,
                    capability_id,
                    version,
                    int(is_executable),
                    implementation_ref,
                    combination_logic_ref,
                    json.dumps(snapshot, sort_keys=True),
                    ts,
                ),
            )
            total += 1
            if is_executable:
                executable_ready += 1

        return {
            "candidate_count": total,
            "executable_candidate_count": executable_ready,
        }

    def list_draft_publication_candidates(
        self,
        draft_id: str,
    ) -> list[CapabilityPublicationCandidateRecord]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM capability_publication_candidates
                WHERE draft_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (draft_id,),
            ).fetchall()
        return [CapabilityPublicationCandidateRecord.from_row(row) for row in rows]

    def list_publication_candidates_for_history(
        self,
        history_id: str,
    ) -> list[CapabilityPublicationCandidateRecord]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM capability_publication_candidates
                WHERE history_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (history_id,),
            ).fetchall()
        return [CapabilityPublicationCandidateRecord.from_row(row) for row in rows]


__all__ = ["CapabilityPublicationService"]
