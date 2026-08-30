"""
CapabilityPackageService — package-first API surface.

A capability package is the first-class sovereign object that owns both its
implementation source truth (unpublished surface) and its published artifacts
(published surface), plus its immutable record event history.

Two primary surfaces per package:

  published    — what is executing right now: installed capability record plus
                 package-owned published artifact files indexed in
                 capability_published_forms.

  unpublished  — the in-progress proposed change (from capability_drafts /
                 capability_draft_items), or None if no open draft.

The published surface is the observable, read-only face of installed truth.
The unpublished surface is the editable face of proposed change.

Bootstrap-regime exception: builtins resolve via execution_source='binding_ref'
because their source lives in a Python module. They still resolve into the same
package model — same surfaces, same history, same dataclasses. The distinction
is only in execution_source and source maintenance (Python module vs stored
code_block).

Consumer compatibility: consumers couple to requested package-surface contracts,
not to internal artifact layout. Internal path structure may evolve without
breaking consumers unless the surface contract they depend on changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from reveng.storage.db_connection import get_db
from reveng.platform.services.capability_catalog_service import (
    CapabilityCatalogService,
    CapabilityRecordNotFoundError,
)


@dataclass
class CapabilityPublishedForm:
    form_id: str
    form_kind: str          # 'python_artifact' | 'json_snapshot' | 'text_summary'
    artifact_path: str      # path to the package-owned published file
    publish_event_id: str
    created_at: str


@dataclass
class CapabilityPublishedSurface:
    capability_id: str
    display_name: str
    description: str
    capability_type: str
    execution_source: str
    code_block: str
    pack_id: str
    version: str
    contract: dict[str, Any]
    tags: list[str]
    icon: str | None
    lifecycle_state: str
    source_kind: str
    implementation_ref: str | None
    combination_logic_ref: str | None
    component_capabilities: list[str]
    execution_order: list[str]
    entrypoint: str
    publish_outputs: list[str]
    package_object_id: str | None
    published_forms: list[CapabilityPublishedForm] = field(default_factory=list)


@dataclass
class CapabilityUnpublishedSurface:
    draft_id: str
    draft_name: str
    item_id: str
    draft_data: dict[str, Any]
    status: str

    # Convenience accessors derived from draft_data
    @property
    def capability_id(self) -> str:
        return self.draft_data.get("capability_id", "")

    @property
    def display_name(self) -> str:
        return self.draft_data.get("display_name", "")

    @property
    def code_block(self) -> str:
        return self.draft_data.get("code_block", "")

    @property
    def entrypoint(self) -> str:
        return self.draft_data.get("entrypoint") or "run"

    @property
    def execution_source(self) -> str:
        return self.draft_data.get("execution_source") or "binding_ref"

    @property
    def publish_outputs(self) -> list[str]:
        return list(self.draft_data.get("publish_outputs") or ["python_artifact", "text_summary"])


@dataclass
class CapabilityHistoryEntry:
    event_id: str
    event_type: str
    source_kind: str
    source_ref: str
    snapshot_data: dict[str, Any]
    created_at: str


@dataclass
class CapabilityPackage:
    capability_id: str
    published: CapabilityPublishedSurface
    unpublished: CapabilityUnpublishedSurface | None
    history: list[CapabilityHistoryEntry]


class CapabilityPackageService:
    """
    Package API (read + write).  Assembles the two surfaces and history for
    any installed capability, and provides package-centered write operations
    that delegate to the underlying draft/publication services.
    """

    def __init__(self, catalog: CapabilityCatalogService) -> None:
        self._catalog = catalog

    def get_package(self, capability_id: str) -> CapabilityPackage:
        """
        Return the full package for *capability_id*.

        Raises CapabilityRecordNotFoundError if the capability is not installed.
        """
        record = self._catalog.get_installed_record_or_raise(capability_id)

        published_forms = self._get_published_forms(capability_id)
        published = CapabilityPublishedSurface(
            capability_id=record.capability_id,
            display_name=record.display_name,
            description=record.description,
            capability_type=record.capability_type,
            execution_source=record.execution_source,
            code_block=record.code_block,
            pack_id=record.pack_id,
            version=record.version,
            contract=record.contract,
            tags=list(record.tags),
            icon=record.icon,
            lifecycle_state=record.lifecycle_state,
            source_kind=record.source_kind,
            implementation_ref=record.implementation_ref,
            combination_logic_ref=record.combination_logic_ref,
            component_capabilities=list(record.component_capabilities),
            execution_order=list(record.execution_order),
            entrypoint=record.entrypoint,
            publish_outputs=list(record.publish_outputs),
            package_object_id=record.package_object_id,
            published_forms=published_forms,
        )

        unpublished = self._get_unpublished_surface(capability_id)
        history = self._get_history(capability_id)

        return CapabilityPackage(
            capability_id=capability_id,
            published=published,
            unpublished=unpublished,
            history=history,
        )

    def get_body(self, capability_id: str) -> str:
        """Return just the code_block for *capability_id*."""
        record = self._catalog.get_installed_record_or_raise(capability_id)
        return record.code_block

    def get_published_forms(self, capability_id: str) -> list[CapabilityPublishedForm]:
        """Return all capability_published_forms rows for *capability_id*."""
        self._catalog.get_installed_record_or_raise(capability_id)  # 404 guard
        return self._get_published_forms(capability_id)

    def get_history(self, capability_id: str) -> list[CapabilityHistoryEntry]:
        """Return the full record event ledger for *capability_id*."""
        self._catalog.get_installed_record_or_raise(capability_id)  # 404 guard
        return self._get_history(capability_id)

    # ------------------------------------------------------------------
    # Write operations (delegate to draft / publication services)
    # ------------------------------------------------------------------

    def propose(
        self,
        capability_id: str,
        draft_data: dict[str, Any],
        *,
        draft_service,
    ) -> dict[str, Any]:
        """
        Open a draft for *capability_id* with the supplied *draft_data*.

        Returns dict with keys: draft_id, item_id, planned_capability_id.
        """
        self._catalog.get_installed_record_or_raise(capability_id)  # 404 guard

        draft_data = dict(draft_data)
        draft_data.setdefault("capability_id", capability_id)

        draft = draft_service.create_draft(
            name=f"Package edit: {capability_id}",
            description=f"Single-capability edit for {capability_id}",
        )
        item = draft_service.add_draft_item(
            draft.id,
            planned_capability_id=capability_id,
            draft_data=draft_data,
        )
        return {
            "draft_id": draft.id,
            "item_id": item.id,
            "planned_capability_id": capability_id,
        }

    def validate_draft_for(
        self,
        capability_id: str,
        *,
        draft_service,
    ) -> dict[str, Any]:
        """
        Validate the most recent open draft for *capability_id*.

        Returns the full validate_draft result dict.  Raises ValueError if no
        open draft exists.
        """
        unpublished = self._get_unpublished_surface(capability_id)
        if unpublished is None:
            raise ValueError(f"No open draft found for capability {capability_id!r}")
        return draft_service.validate_draft(unpublished.draft_id)

    def publish_draft_for(
        self,
        capability_id: str,
        *,
        draft_service,
    ) -> dict[str, Any]:
        """
        Publish the most recent open draft for *capability_id*.

        Returns the full publish_draft result dict.  Raises ValueError if no
        open draft exists.
        """
        unpublished = self._get_unpublished_surface(capability_id)
        if unpublished is None:
            raise ValueError(f"No open draft found for capability {capability_id!r}")
        return draft_service.publish_draft(unpublished.draft_id)

    def rollback_to_publication(
        self,
        capability_id: str,
        history_id: str,
        *,
        draft_service,
    ) -> dict[str, Any]:
        """
        Roll back *capability_id* to the snapshot recorded at *history_id*.

        *history_id* is a ``capability_record_events.id`` value.

        Creates a new single-item rollback draft from the historical snapshot,
        validates it, and publishes it through the normal installation path.
        Returns the publish result dict extended with rollback metadata.
        """
        self._catalog.get_installed_record_or_raise(capability_id)  # 404 guard
        history = self._get_history(capability_id)

        history_entry = next((e for e in history if e.event_id == history_id), None)
        if history_entry is None:
            raise ValueError(
                f"History event {history_id!r} not found in record for {capability_id!r}"
            )

        snapshot_data = dict(history_entry.snapshot_data)
        snapshot_data.setdefault("capability_id", capability_id)

        rollback_draft = draft_service.create_draft(
            name=f"Package rollback: {capability_id}",
            description=(
                f"Rollback of {capability_id} to "
                f"{history_entry.event_type} snapshot from "
                f"{history_entry.created_at[:10]}"
            ),
        )
        draft_service.add_draft_item(
            rollback_draft.id,
            planned_capability_id=capability_id,
            draft_data=snapshot_data,
        )

        validate_result = draft_service.validate_draft(rollback_draft.id)
        if validate_result.get("failed", 0) > 0:
            failed_items = [
                r for r in validate_result.get("results", []) if not r.get("passed")
            ]
            violations = "; ".join(
                v
                for item in failed_items
                for v in item.get("violations", [])
            )
            return {
                "ok": False,
                "error": violations or "Rollback validation failed",
                "draft_id": rollback_draft.id,
            }

        publish_result = draft_service.publish_draft(rollback_draft.id)
        return {
            **publish_result,
            "rollback_event_id": history_id,
            "rollback_event_type": history_entry.event_type,
            "rollback_snapshot_date": history_entry.created_at[:10],
        }

    def discard_draft_for(
        self,
        capability_id: str,
        *,
        draft_service,
    ) -> None:
        """
        Discard (delete) the most recent open draft for *capability_id*.

        Raises ValueError if no open draft exists.
        """
        unpublished = self._get_unpublished_surface(capability_id)
        if unpublished is None:
            raise ValueError(f"No open draft found for capability {capability_id!r}")
        draft_service.delete_draft(unpublished.draft_id)

    def publish_changeset(
        self,
        capability_ids: list[str],
        *,
        draft_service,
    ) -> dict[str, Any]:
        """
        Publish all open draft items for the listed capability IDs as a
        coordinated batch.  Creates a single new draft containing all items,
        then publishes it atomically.

        Returns the publish_draft result dict for the batch draft.
        """
        items_to_include: list[dict[str, Any]] = []
        for cap_id in capability_ids:
            unpublished = self._get_unpublished_surface(cap_id)
            if unpublished is None:
                raise ValueError(f"No open draft found for capability {cap_id!r}")
            items_to_include.append({
                "draft_id": unpublished.draft_id,
                "item_id": unpublished.item_id,
                "draft_data": unpublished.draft_data,
                "capability_id": cap_id,
            })

        batch_draft = draft_service.create_draft(
            name=f"Changeset: {', '.join(capability_ids[:3])}{'...' if len(capability_ids) > 3 else ''}",
            description=f"Coordinated publication of {len(capability_ids)} capability package(s)",
        )
        for item_info in items_to_include:
            draft_service.add_draft_item(
                batch_draft.id,
                planned_capability_id=item_info["capability_id"],
                draft_data=item_info["draft_data"],
            )

        return draft_service.publish_draft(batch_draft.id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_unpublished_surface(self, capability_id: str) -> CapabilityUnpublishedSurface | None:
        """Find the most recent open draft item for this capability, if any."""
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT
                    di.id          AS item_id,
                    di.draft_id,
                    di.draft_data,
                    di.item_state  AS status,
                    d.name         AS draft_name
                FROM capability_draft_items di
                JOIN capability_drafts d ON d.id = di.draft_id
                WHERE di.planned_capability_id = ?
                  AND di.item_state NOT IN ('published', 'discarded')
                ORDER BY di.created_at DESC
                LIMIT 1
                """,
                (capability_id,),
            ).fetchone()
        if row is None:
            return None
        return CapabilityUnpublishedSurface(
            draft_id=row["draft_id"],
            draft_name=row["draft_name"],
            item_id=row["item_id"],
            draft_data=json.loads(row["draft_data"] or "{}"),
            status=row["status"],
        )

    def _get_published_forms(self, capability_id: str) -> list[CapabilityPublishedForm]:
        """Return all published form rows for this capability, newest first."""
        try:
            with get_db() as conn:
                rows = conn.execute(
                    """
                    SELECT id, form_kind, artifact_path, publish_event_id, created_at
                    FROM capability_published_forms
                    WHERE capability_id = ?
                    ORDER BY created_at DESC
                    """,
                    (capability_id,),
                ).fetchall()
        except Exception:
            # Table may not exist on older DB schema (pre-migration).
            return []
        return [
            CapabilityPublishedForm(
                form_id=row["id"],
                form_kind=row["form_kind"],
                artifact_path=row["artifact_path"] or "",
                publish_event_id=row["publish_event_id"] or "",
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _get_history(self, capability_id: str) -> list[CapabilityHistoryEntry]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT id, event_type, source_kind, source_ref, snapshot_json, created_at
                FROM capability_record_events
                WHERE capability_id = ?
                ORDER BY created_at ASC
                """,
                (capability_id,),
            ).fetchall()
        entries = []
        for row in rows:
            snapshot_data = json.loads(row["snapshot_json"] or "{}")
            # Normalize legacy capability_type values at presentation time.
            # Stored historical records are intentionally left unchanged (immutable audit log).
            ct = snapshot_data.get("capability_type")
            if ct == "base":
                snapshot_data["capability_type"] = "function"
            elif ct == "combination":
                snapshot_data["capability_type"] = "composite"
            entries.append(CapabilityHistoryEntry(
                event_id=row["id"],
                event_type=row["event_type"],
                source_kind=row["source_kind"],
                source_ref=row["source_ref"],
                snapshot_data=snapshot_data,
                created_at=row["created_at"],
            ))
        return entries


__all__ = [
    "CapabilityPackageService",
    "CapabilityPackage",
    "CapabilityPublishedSurface",
    "CapabilityPublishedForm",
    "CapabilityUnpublishedSurface",
    "CapabilityHistoryEntry",
    # Legacy names kept for any import that hasn't been updated yet
    "CapabilityLiveFace",
    "CapabilityDraftFace",
    "CapabilityPackageView",
]

# Legacy aliases — removed in Phase 9 consumer cleanup
CapabilityLiveFace = CapabilityPublishedSurface
CapabilityDraftFace = CapabilityUnpublishedSurface
CapabilityPackageView = CapabilityPackage
