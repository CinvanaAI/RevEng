"""
CapabilityDraftService owns platform-side CapabilityDraft authority.

Capability drafts are non-live capability work units. This service owns draft
CRUD, item editing, saved working-version snapshots, validation, publication
history, and export handoff generation. Environment objects may orchestrate
those operations, but they do not own draft truth.
"""
from __future__ import annotations

import json
import textwrap
import uuid
from typing import Any

from reveng.platform.capability_combination_logic import (
    binding_ref_for_combination_logic_kind,
    resolve_combination_logic,
)
from reveng.platform.models.capability_draft import (
    CAPABILITY_DRAFT_STATES,
    CapabilityDraftItem,
    CapabilityDraftNotFoundError,
    CapabilityDraftPublicationRecord,
    CapabilityDraftRecord,
    CapabilityDraftRevisionRecord,
    CapabilityDraftSpec,
)
from reveng.platform.models.capability_publication import CapabilityPublicationCandidateRecord
from reveng.storage.db_connection import get_db
from reveng.platform.services.capability_catalog_service import CapabilityCatalogService
from reveng.platform.services.capability_publication_service import CapabilityPublicationService
from reveng.platform.utils import now_utc

COMBINATION_LOGIC_KINDS: dict[str, str] = {
    "merge": (
        "Merge all component outputs into a single flat dict. "
        "Later outputs overwrite earlier ones on key collision."
    ),
    "first": (
        "Return the output dict from the first component in execution_order."
    ),
    "collect": (
        "Collect outputs under their capability_id. "
        "Returns {capability_id: output_dict}."
    ),
}


class CapabilityDraftService:
    def __init__(
        self,
        capability_catalog: CapabilityCatalogService | None = None,
        publication_service: CapabilityPublicationService | None = None,
    ) -> None:
        self._capability_catalog = capability_catalog or CapabilityCatalogService()
        self._publication_service = publication_service or CapabilityPublicationService()

    # ------------------------------------------------------------------
    # CapabilityDraft CRUD
    # ------------------------------------------------------------------

    def create_draft(
        self,
        *,
        name: str,
        description: str = "",
        version: str = "1.0.0",
    ) -> CapabilityDraftRecord:
        draft_id = str(uuid.uuid4())
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO capability_drafts
                    (id, name, description, lifecycle_state, version, created_at, updated_at)
                VALUES (?, ?, ?, 'draft', ?, ?, ?)
                """,
                (draft_id, name.strip(), description.strip(), version.strip(), ts, ts),
            )
            conn.commit()
        return self.get_draft_or_raise(draft_id)

    def get_draft(self, draft_id: str) -> CapabilityDraftRecord | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM capability_drafts WHERE id = ?",
                (draft_id,),
            ).fetchone()
        return CapabilityDraftRecord.from_row(row) if row else None

    def get_draft_or_raise(self, draft_id: str) -> CapabilityDraftRecord:
        record = self.get_draft(draft_id)
        if record is None:
            raise CapabilityDraftNotFoundError(f"CapabilityDraft not found: {draft_id!r}")
        return record

    def list_drafts(self) -> list[CapabilityDraftRecord]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM capability_drafts ORDER BY created_at DESC"
            ).fetchall()
        return [CapabilityDraftRecord.from_row(row) for row in rows]

    def update_draft(
        self,
        draft_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> CapabilityDraftRecord:
        draft = self.get_draft_or_raise(draft_id)
        ts = now_utc()
        new_name = name.strip() if name is not None else draft.name
        new_description = description.strip() if description is not None else draft.description
        with get_db() as conn:
            conn.execute(
                """
                UPDATE capability_drafts
                SET name=?, description=?, updated_at=?
                WHERE id=?
                """,
                (new_name, new_description, ts, draft_id),
            )
            conn.commit()
        return self.get_draft_or_raise(draft_id)

    def save_draft_version(
        self,
        draft_id: str,
        *,
        version: str,
    ) -> CapabilityDraftRevisionRecord:
        draft = self.get_draft_or_raise(draft_id)
        if draft.lifecycle_state != "draft":
            raise ValueError("Only active draft-state drafts can save a new working version.")

        new_version = version.strip()
        if not new_version:
            raise ValueError("Draft version is required.")
        if new_version == draft.version:
            raise ValueError("New draft version must differ from the current version.")

        existing_versions = {
            record.version for record in self.get_draft_revision_history(draft_id)
        }
        if new_version in existing_versions:
            raise ValueError(f"Draft version already exists in saved workbench history: {new_version!r}")

        spec = self.get_draft_spec(draft_id)
        revision_id = str(uuid.uuid4())
        ts = now_utc()
        snapshot_data = self._build_draft_snapshot_data(spec, version=new_version, saved_at=ts)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO capability_draft_revisions
                    (id, draft_id, version, name, description, saved_at, item_count, snapshot_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    draft_id,
                    new_version,
                    spec.draft.name,
                    spec.draft.description,
                    ts,
                    len(spec.items),
                    json.dumps(snapshot_data),
                ),
            )
            conn.execute(
                """
                UPDATE capability_drafts
                SET version=?, updated_at=?
                WHERE id=?
                """,
                (new_version, ts, draft_id),
            )
            conn.commit()

        return self.get_draft_revision_or_raise(revision_id)

    def set_draft_lifecycle_state(self, draft_id: str, state: str) -> CapabilityDraftRecord:
        if state not in CAPABILITY_DRAFT_STATES:
            raise ValueError(f"Invalid CapabilityDraft lifecycle state: {state!r}")
        self.get_draft_or_raise(draft_id)
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                "UPDATE capability_drafts SET lifecycle_state=?, updated_at=? WHERE id=?",
                (state, ts, draft_id),
            )
            conn.commit()
        return self.get_draft_or_raise(draft_id)

    def delete_draft(self, draft_id: str) -> None:
        self.get_draft_or_raise(draft_id)
        with get_db() as conn:
            conn.execute("DELETE FROM capability_drafts WHERE id = ?", (draft_id,))
            conn.commit()

    def get_draft_spec(self, draft_id: str) -> CapabilityDraftSpec:
        draft = self.get_draft_or_raise(draft_id)
        items = self.list_draft_items(draft_id)
        return CapabilityDraftSpec(draft=draft, items=items)

    # ------------------------------------------------------------------
    # Working version history
    # ------------------------------------------------------------------

    def get_draft_revision(self, revision_id: str) -> CapabilityDraftRevisionRecord | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM capability_draft_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
        return CapabilityDraftRevisionRecord.from_row(row) if row else None

    def get_draft_revision_or_raise(self, revision_id: str) -> CapabilityDraftRevisionRecord:
        revision = self.get_draft_revision(revision_id)
        if revision is None:
            raise KeyError(f"Draft revision not found: {revision_id!r}")
        return revision

    def get_draft_revision_history(
        self,
        draft_id: str,
    ) -> list[CapabilityDraftRevisionRecord]:
        self.get_draft_or_raise(draft_id)
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM capability_draft_revisions
                WHERE draft_id = ?
                ORDER BY saved_at DESC
                """,
                (draft_id,),
            ).fetchall()
        return [CapabilityDraftRevisionRecord.from_row(row) for row in rows]

    def rollback_draft_to_revision(
        self,
        draft_id: str,
        revision_id: str,
    ) -> dict[str, Any]:
        revision = self.get_draft_revision_or_raise(revision_id)
        if revision.draft_id != draft_id:
            raise KeyError(f"Draft revision not found for draft: {revision_id!r}")

        snapshot = dict(revision.snapshot_data)
        snapshot_draft = dict(snapshot.get("draft", {}))
        snapshot_items = list(snapshot.get("items", []))
        return self._rollback_snapshot_to_live(
            draft_id=draft_id,
            source_kind="draft_revision",
            source_id=revision.id,
            source_version=revision.version,
            source_label=f"saved revision v{revision.version}",
            source_name=snapshot_draft.get("name") or self.get_draft_or_raise(draft_id).name,
            source_description=snapshot_draft.get("description", "") or "",
            rollback_version=revision.version,
            snapshot_items=snapshot_items,
        )

    # ------------------------------------------------------------------
    # Draft item CRUD
    # ------------------------------------------------------------------

    def add_draft_item(
        self,
        draft_id: str,
        *,
        planned_capability_id: str,
        draft_data: dict[str, Any] | None = None,
    ) -> CapabilityDraftItem:
        self.get_draft_or_raise(draft_id)
        item_id = str(uuid.uuid4())
        ts = now_utc()
        data_json = json.dumps(draft_data or {})
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO capability_draft_items
                    (id, draft_id, planned_capability_id, draft_data,
                     item_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'draft', ?, ?)
                """,
                (item_id, draft_id, planned_capability_id.strip(), data_json, ts, ts),
            )
            conn.commit()
        return self.get_draft_item_or_raise(item_id)

    def get_draft_item(self, item_id: str) -> CapabilityDraftItem | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM capability_draft_items WHERE id = ?",
                (item_id,),
            ).fetchone()
        return CapabilityDraftItem.from_row(row) if row else None

    def get_draft_item_or_raise(self, item_id: str) -> CapabilityDraftItem:
        item = self.get_draft_item(item_id)
        if item is None:
            raise KeyError(f"Draft item not found: {item_id!r}")
        return item

    def list_draft_items(self, draft_id: str) -> list[CapabilityDraftItem]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM capability_draft_items
                WHERE draft_id = ?
                ORDER BY created_at ASC
                """,
                (draft_id,),
            ).fetchall()
        return [CapabilityDraftItem.from_row(row) for row in rows]

    def update_draft_item(
        self,
        item_id: str,
        *,
        planned_capability_id: str | None = None,
        draft_data: dict[str, Any] | None = None,
    ) -> CapabilityDraftItem:
        item = self.get_draft_item_or_raise(item_id)
        ts = now_utc()
        new_capability_id = (
            planned_capability_id.strip()
            if planned_capability_id is not None
            else item.planned_capability_id
        )
        new_data = json.dumps(draft_data if draft_data is not None else item.draft_data)
        with get_db() as conn:
            conn.execute(
                """
                UPDATE capability_draft_items
                SET planned_capability_id=?, draft_data=?, item_state='draft',
                    updated_at=?
                WHERE id=?
                """,
                (new_capability_id, new_data, ts, item_id),
            )
            conn.commit()
        return self.get_draft_item_or_raise(item_id)

    def remove_draft_item(self, item_id: str) -> None:
        self.get_draft_item_or_raise(item_id)
        with get_db() as conn:
            conn.execute("DELETE FROM capability_draft_items WHERE id = ?", (item_id,))
            conn.commit()

    # ------------------------------------------------------------------
    # Environment-level validation
    # ------------------------------------------------------------------

    def validate_draft(self, draft_id: str) -> dict[str, Any]:
        """
        Run Capability Platform validation rules against each draft item in a
        CapabilityDraft.

        Items that pass validation move to `validated`. Items that fail remain
        in `draft`.
        """
        from reveng.platform.capabilities import (
            CapabilityContract,
            CapabilityDefinition,
            validate_capability,
        )

        items = self.list_draft_items(draft_id)
        results: list[dict[str, Any]] = []
        ts = now_utc()
        installed_ids = set(self._capability_catalog.list_installed_capability_ids())
        duplicate_ids = self._duplicate_publish_capability_ids(items)

        for item in items:
            violations: list[str]
            data = item.draft_data
            capability_id = data.get("capability_id") or item.planned_capability_id
            try:
                contract_data = data.get("contract", {})
                contract = CapabilityContract(
                    inputs=tuple(contract_data.get("inputs", [])),
                    output=tuple(contract_data.get("output", [])),
                    constraints=tuple(contract_data.get("constraints", [])),
                )
                cap_type = data.get("capability_type", "")
                if cap_type == "base":
                    cap_type = "function"
                elif cap_type == "combination":
                    cap_type = "composite"
                combination = (
                    self._build_combination_spec(data)
                    if cap_type == "composite"
                    else None
                )
                definition = CapabilityDefinition(
                    capability_id=data.get("capability_id", ""),
                    pack_id=data.get("pack_id", "environment"),
                    version=data.get("version", "1"),
                    display_name=data.get("display_name", ""),
                    description=data.get("description", ""),
                    capability_type=cap_type,
                    contract=contract,
                    implementation_logic=data.get("implementation_logic"),
                    combination=combination,
                    icon=data.get("icon"),
                    tags=tuple(data.get("tags", [])),
                )
                violations = validate_capability(definition)
                violations = [
                    violation
                    for violation in violations
                    if "implementation_logic" not in violation
                ]
                violations.extend(self._installability_violations_for_item(item))
                if capability_id in duplicate_ids:
                    violations.append(
                        "capability_id duplicates another draft item in the same publish batch: "
                        f"{capability_id!r}"
                    )
                if cap_type == "composite":
                    known_ids = {draft_item.planned_capability_id for draft_item in items} | installed_ids
                    for component_id in data.get("component_capabilities", []):
                        if component_id not in known_ids:
                            violations.append(
                                "component capability not found in draft or installed platform inventory: "
                                f"{component_id!r}"
                            )
            except Exception as exc:
                violations = [f"Could not construct definition: {exc}"]

            passed = len(violations) == 0
            new_state = "validated" if passed else "draft"
            with get_db() as conn:
                conn.execute(
                    "UPDATE capability_draft_items SET item_state=?, updated_at=? WHERE id=?",
                    (new_state, ts, item.id),
                )
                conn.commit()

            results.append(
                {
                    "item_id": item.id,
                    "planned_capability_id": item.planned_capability_id,
                    "passed": passed,
                    "violations": violations,
                }
            )

        passed_count = sum(1 for result in results if result["passed"])
        return {
            "draft_id": draft_id,
            "total": len(results),
            "passed": passed_count,
            "failed": len(results) - passed_count,
            "results": results,
        }

    # ------------------------------------------------------------------
    # Publication
    # ------------------------------------------------------------------

    def publish_draft(self, draft_id: str) -> dict[str, Any]:
        """
        Mark the CapabilityDraft and all validated items as published.

        This installs the published draft items into live Capability Platform
        truth through the platform-owned catalog.
        """
        draft = self.get_draft_or_raise(draft_id)
        if draft.lifecycle_state == "retired":
            return {"ok": False, "error": "Cannot publish a retired draft."}

        items = self.list_draft_items(draft_id)
        unvalidated = [item for item in items if item.item_state == "draft"]
        if unvalidated:
            return {
                "ok": False,
                "error": (
                    f"{len(unvalidated)} item(s) have not been validated. "
                    "Run validation before publishing."
                ),
                "unvalidated_item_ids": [item.id for item in unvalidated],
            }

        ts = now_utc()
        history_id = str(uuid.uuid4())
        publishable_items = [item for item in items if item.item_state == "validated"]
        item_count = len(publishable_items)
        duplicate_ids = self._duplicate_publish_capability_ids(publishable_items)
        if duplicate_ids:
            return {
                "ok": False,
                "error": (
                    "Publish batch contains duplicate capability IDs. "
                    f"Each live installed capability must resolve to one record: {sorted(duplicate_ids)!r}"
                ),
            }

        non_installable_items = self._non_installable_publish_items(publishable_items)
        if non_installable_items:
            return {
                "ok": False,
                "error": (
                    "Publish requires executable-ready draft items before replacing live installed truth."
                ),
                "non_installable_capability_ids": non_installable_items,
            }

        with get_db() as conn:
            conn.execute(
                """
                UPDATE capability_draft_items
                SET item_state='published', updated_at=?
                WHERE draft_id=? AND item_state='validated'
                """,
                (ts, draft_id),
            )
            conn.execute(
                "UPDATE capability_drafts SET lifecycle_state='published', updated_at=? WHERE id=?",
                (ts, draft_id),
            )
            conn.execute(
                """
                INSERT INTO capability_draft_publication_history
                    (id, draft_id, version, published_at, item_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (history_id, draft_id, draft.version, ts, item_count),
            )
            candidate_summary = self._publication_service.record_draft_publication_candidates(
                conn=conn,
                draft=draft,
                items=publishable_items,
                history_id=history_id,
            )
            install_summary = self._capability_catalog.install_published_draft_items(
                conn=conn,
                draft=draft,
                items=publishable_items,
                history_id=history_id,
            )
            conn.commit()

        return {
            "ok": True,
            "draft_id": draft_id,
            "version": draft.version,
            "published_item_count": item_count,
            "history_id": history_id,
            "publication_candidate_count": candidate_summary["candidate_count"],
            "executable_candidate_count": candidate_summary["executable_candidate_count"],
            "installed_live_count": install_summary["installed_live_count"],
            "replaced_live_count": install_summary["replaced_live_count"],
        }

    # ------------------------------------------------------------------
    # Publication history
    # ------------------------------------------------------------------

    def get_draft_publication_history(
        self,
        draft_id: str,
    ) -> list[CapabilityDraftPublicationRecord]:
        self.get_draft_or_raise(draft_id)
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM capability_draft_publication_history
                WHERE draft_id = ?
                ORDER BY published_at DESC
                """,
                (draft_id,),
            ).fetchall()
        return [CapabilityDraftPublicationRecord.from_row(row) for row in rows]

    def get_draft_publication_record(
        self,
        history_id: str,
    ) -> CapabilityDraftPublicationRecord | None:
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT * FROM capability_draft_publication_history
                WHERE id = ?
                """,
                (history_id,),
            ).fetchone()
        return CapabilityDraftPublicationRecord.from_row(row) if row else None

    def get_draft_publication_record_or_raise(
        self,
        history_id: str,
    ) -> CapabilityDraftPublicationRecord:
        record = self.get_draft_publication_record(history_id)
        if record is None:
            raise KeyError(f"Draft publication record not found: {history_id!r}")
        return record

    def get_draft_publication_candidates(
        self,
        draft_id: str,
    ) -> list[CapabilityPublicationCandidateRecord]:
        self.get_draft_or_raise(draft_id)
        return self._publication_service.list_draft_publication_candidates(draft_id)

    def rollback_draft_to_publication(
        self,
        draft_id: str,
        history_id: str,
    ) -> dict[str, Any]:
        publication = self.get_draft_publication_record_or_raise(history_id)
        if publication.draft_id != draft_id:
            raise KeyError(f"Draft publication record not found for draft: {history_id!r}")

        candidates = self._publication_service.list_publication_candidates_for_history(history_id)
        snapshot_items = [
            dict(candidate.snapshot_data.get("item", {}))
            for candidate in candidates
        ]
        draft = self.get_draft_or_raise(draft_id)
        return self._rollback_snapshot_to_live(
            draft_id=draft_id,
            source_kind="draft_publication",
            source_id=publication.id,
            source_version=publication.version,
            source_label=f"published version v{publication.version}",
            source_name=draft.name,
            source_description=draft.description,
            rollback_version=publication.version,
            snapshot_items=snapshot_items,
        )

    # ------------------------------------------------------------------
    # Platform handoff
    # ------------------------------------------------------------------

    def export_draft_as_pack_snippet(self, draft_id: str) -> str:
        """
        Generate a Python pack snippet for validated or published draft items.
        """
        spec = self.get_draft_spec(draft_id)
        exportable = [
            item for item in spec.items
            if item.item_state in ("validated", "published")
        ]

        lines = [
            '"""',
            f"Auto-generated pack snippet from draft: {spec.draft.name!r}",
            f"Draft ID:  {spec.draft.id}",
            f"Version:   {spec.draft.version}",
            '"""',
            "from reveng.platform.capabilities import CapabilityContract, CapabilityDefinition, CapabilityRegistry, CombinationSpec",
            "",
            "",
            textwrap.dedent(
                """
                def _combination_logic(kind: str):
                    if kind == "merge":
                        return lambda payload: dict(payload.get("merged", {}))
                    if kind == "first":
                        def _first(payload):
                            order = payload.get("execution_order", ())
                            per_component = payload.get("per_component", {})
                            if not order:
                                return {}
                            return dict(per_component.get(order[0], {}))
                        return _first
                    if kind == "collect":
                        return lambda payload: dict(payload.get("per_component", {}))
                    raise ValueError(f"Unsupported combination_logic_kind: {kind!r}")
                """
            ).strip(),
            "",
            "",
            "def register(registry: CapabilityRegistry) -> None:",
        ]

        if not exportable:
            lines.append("    pass  # no exportable items in this draft")
        else:
            for item in exportable:
                draft_data = item.draft_data
                capability_id = draft_data.get("capability_id") or item.planned_capability_id
                cap_type = draft_data.get("capability_type", "function")
                if cap_type == "base":
                    cap_type = "function"
                elif cap_type == "combination":
                    cap_type = "composite"
                display_name = draft_data.get("display_name", capability_id)
                description = draft_data.get("description", "")
                contract_data = draft_data.get("contract", {})
                inputs_repr = repr(tuple(contract_data.get("inputs", [])))
                output_repr = repr(tuple(contract_data.get("output", [])))
                constraints_repr = repr(tuple(contract_data.get("constraints", [])))
                tags_repr = repr(tuple(draft_data.get("tags", [])))
                version = draft_data.get("version", spec.draft.version)
                pack_id = draft_data.get("pack_id", f"draft.{spec.draft.id[:8]}")

                lines.append(f"    # --- {capability_id} ---")
                lines.append("    registry.register(CapabilityDefinition(")
                lines.append(f"        capability_id={capability_id!r},")
                lines.append(f"        pack_id={pack_id!r},")
                lines.append(f"        version={version!r},")
                lines.append(f"        display_name={display_name!r},")
                lines.append(f"        description={description!r},")
                lines.append(f"        capability_type={cap_type!r},")
                lines.append("        contract=CapabilityContract(")
                lines.append(f"            inputs={inputs_repr},")
                lines.append(f"            output={output_repr},")
                lines.append(f"            constraints={constraints_repr},")
                lines.append("        ),")
                if cap_type == "function":
                    lines.append("        implementation_logic=None,  # TODO: wire handler")
                else:
                    component_ids = tuple(draft_data.get("component_capabilities", []))
                    execution_order = tuple(draft_data.get("execution_order", component_ids))
                    logic_kind = draft_data.get("combination_logic_kind", "merge")
                    lines.append("        combination=CombinationSpec(")
                    lines.append(f"            component_capabilities={component_ids!r},")
                    lines.append(f"            execution_order={execution_order!r},")
                    lines.append(f"            combination_logic=_combination_logic({logic_kind!r}),")
                    lines.append("        ),")
                lines.append(f"        tags={tags_repr},")
                lines.append("    ))")
                lines.append("")

        return "\n".join(lines)

    def _build_combination_spec(self, draft_data: dict[str, Any]):
        from reveng.platform.capabilities import CombinationSpec

        component_capabilities = tuple(draft_data.get("component_capabilities", []))
        execution_order = tuple(draft_data.get("execution_order", component_capabilities))
        logic_kind = draft_data.get("combination_logic_kind", "merge")

        return CombinationSpec(
            component_capabilities=component_capabilities,
            execution_order=execution_order,
            combination_logic=resolve_combination_logic(logic_kind),
        )

    def _duplicate_publish_capability_ids(self, items: list[CapabilityDraftItem]) -> set[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for item in items:
            capability_id = item.draft_data.get("capability_id") or item.planned_capability_id
            if capability_id in seen:
                duplicates.add(capability_id)
            seen.add(capability_id)
        return duplicates

    def _non_installable_publish_items(self, items: list[CapabilityDraftItem]) -> list[str]:
        not_ready: list[str] = []
        for item in items:
            capability_id = item.draft_data.get("capability_id") or item.planned_capability_id
            if self._installability_violations_for_item(item):
                not_ready.append(capability_id)
        return not_ready

    def _installability_violations_for_item(self, item: CapabilityDraftItem) -> list[str]:
        draft_data = dict(item.draft_data)
        capability_type = draft_data.get("capability_type", "function")
        if capability_type == "base":
            capability_type = "function"
        elif capability_type == "combination":
            capability_type = "composite"
        execution_source = draft_data.get("execution_source", "binding_ref")
        implementation_ref = draft_data.get("implementation_ref")
        combination_logic_ref = draft_data.get("combination_logic_ref")

        if not combination_logic_ref and capability_type == "composite":
            logic_kind = draft_data.get("combination_logic_kind", "merge")
            try:
                combination_logic_ref = binding_ref_for_combination_logic_kind(logic_kind)
            except ValueError as exc:
                return [str(exc)]

        # code_block-sourced capabilities don't need an implementation_ref —
        # they execute from the stored code_block directly.
        if capability_type == "function" and execution_source == "binding_ref" and not implementation_ref:
            return [
                "Function capabilities must define an implementation_ref before they can validate for publish."
            ]
        if capability_type == "function" and execution_source == "code_block" and not draft_data.get("code_block"):
            return [
                "Function capabilities with execution_source='code_block' must have a non-empty code_block."
            ]
        if capability_type == "composite" and not combination_logic_ref:
            return [
                "Composite capabilities must define combination logic before they can validate for publish."
            ]
        if capability_type == "function" and execution_source == "binding_ref":
            try:
                self._capability_catalog.resolve_binding_ref(implementation_ref)
            except Exception as exc:
                return [
                    "Function capability implementation_ref could not be resolved for publish: "
                    f"{implementation_ref!r} ({exc})"
                ]
        if capability_type == "composite":
            try:
                self._capability_catalog.resolve_binding_ref(combination_logic_ref)
            except Exception as exc:
                return [
                    "Composite capability logic binding could not be resolved for publish: "
                    f"{combination_logic_ref!r} ({exc})"
                ]
        return []

    def _rollback_snapshot_to_live(
        self,
        *,
        draft_id: str,
        source_kind: str,
        source_id: str,
        source_version: str,
        source_label: str,
        source_name: str,
        source_description: str,
        rollback_version: str,
        snapshot_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.get_draft_or_raise(draft_id)
        if not snapshot_items:
            return {
                "ok": False,
                "error": (
                    f"Rollback could not reconstruct any draft items from {source_label}."
                ),
                "rollback_source_kind": source_kind,
                "rollback_source_id": source_id,
                "rollback_source_version": source_version,
            }

        rollback_note = (
            f"Rollback republish created from {source_label} of draft {source_name}."
        )
        rollback_description = source_description.strip()
        if rollback_description:
            rollback_description = f"{rollback_description}\n\n{rollback_note}"
        else:
            rollback_description = rollback_note

        rollback_draft = self.create_draft(
            name=f"{source_name} rollback to {source_version}",
            description=rollback_description,
            version=rollback_version,
        )

        for item in snapshot_items:
            draft_data = dict(item.get("draft_data", {}))
            planned_capability_id = (
                item.get("planned_capability_id")
                or draft_data.get("capability_id")
            )
            if not planned_capability_id:
                return {
                    "ok": False,
                    "error": (
                        f"Rollback snapshot item is missing planned_capability_id for {source_label}."
                    ),
                    "rollback_draft_id": rollback_draft.id,
                    "rollback_source_kind": source_kind,
                    "rollback_source_id": source_id,
                    "rollback_source_version": source_version,
                }
            draft_data["rollback_source_kind"] = source_kind
            draft_data["rollback_source_id"] = source_id
            draft_data["rollback_source_version"] = source_version
            self.add_draft_item(
                rollback_draft.id,
                planned_capability_id=planned_capability_id,
                draft_data=draft_data,
            )

        validation = self.validate_draft(rollback_draft.id)
        if validation["failed"]:
            return {
                "ok": False,
                "error": (
                    f"Rollback snapshot failed validation before republish from {source_label}."
                ),
                "rollback_draft_id": rollback_draft.id,
                "rollback_source_kind": source_kind,
                "rollback_source_id": source_id,
                "rollback_source_version": source_version,
                "validation": validation,
            }

        result = self.publish_draft(rollback_draft.id)
        result["rollback_draft_id"] = rollback_draft.id
        result["rollback_source_kind"] = source_kind
        result["rollback_source_id"] = source_id
        result["rollback_source_version"] = source_version
        return result

    def _build_draft_snapshot_data(
        self,
        spec: CapabilityDraftSpec,
        *,
        version: str,
        saved_at: str,
    ) -> dict[str, Any]:
        return {
            "draft": {
                "id": spec.draft.id,
                "name": spec.draft.name,
                "description": spec.draft.description,
                "lifecycle_state": spec.draft.lifecycle_state,
                "version": version,
                "created_at": spec.draft.created_at,
                "updated_at": spec.draft.updated_at,
            },
            "saved_at": saved_at,
            "items": [
                {
                    "id": item.id,
                    "planned_capability_id": item.planned_capability_id,
                    "draft_data": item.draft_data,
                    "item_state": item.item_state,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                }
                for item in spec.items
            ],
        }
