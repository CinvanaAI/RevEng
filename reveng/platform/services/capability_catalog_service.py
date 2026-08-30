"""
Storage-backed Capability Platform catalog service.

This service owns the durable installed/live capability catalog. Runtime host
composition may project these stored records into a live CapabilityRegistry,
but the registry is not the truth root.
"""
from __future__ import annotations

import importlib
import inspect
import json
import uuid
from typing import Any

from reveng.platform.capabilities import CapabilityDefinition, CapabilityRegistry
from reveng.platform.capability_combination_logic import (
    binding_ref_for_combination_logic_kind,
)
from reveng.platform.capability_published_artifacts import (
    build_text_summary,
    invalidate_published_python_cache,
    write_published_json,
    write_published_python,
    write_published_text,
)
from reveng.storage.db_connection import get_db
from reveng.platform.models.capability_package import CapabilityPackageObject
from reveng.platform.models.capability_record import CapabilityRecord, CapabilityRecordEvent
from reveng.platform.utils import now_utc
from reveng.packs import capability_intake, file_tools
from reveng.analysis_engine.packs import analysis_pipeline, llm_narration, meaning_layer, python_static, reporting


BUILTIN_CAPABILITY_PACK_REGISTRARS = (
    ("reveng.analysis_engine.packs.python_static", python_static.register),
    ("reveng.analysis_engine.packs.reporting", reporting.register),
    ("reveng.analysis_engine.packs.llm_narration", llm_narration.register),
    ("reveng.analysis_engine.packs.meaning_layer", meaning_layer.register),
    ("reveng.packs.file_tools", file_tools.register),
    ("reveng.packs.capability_intake", capability_intake.register),
    ("reveng.analysis_engine.packs.analysis_pipeline", analysis_pipeline.register),
)


class CapabilityRecordNotFoundError(KeyError):
    pass


class CapabilityCatalogService:
    """Platform authority for stored installed/live capability records."""

    def ensure_builtin_catalog(self) -> None:
        if self.count_builtin_records() > 0:
            return
        self.seed_builtin_catalog()

    def seed_builtin_catalog(self) -> dict[str, int]:
        """
        Seed the builtin capability catalog.

        On first boot, writes all capabilities from BUILTIN_CAPABILITY_PACK_REGISTRARS
        into the DB.  On subsequent boots, syncs any changes (added / removed / updated
        capabilities).  The capability_source_registrations table is the durable record
        of which packs are active — additional packs registered via register_source()
        are included in the sync.

        Alias: sync_builtin_catalog() — kept for backward compatibility.
        """
        return self._run_builtin_sync()

    def sync_builtin_catalog(self) -> dict[str, int]:
        """Backward-compatible alias for seed_builtin_catalog()."""
        return self._run_builtin_sync()

    def _run_builtin_sync(self) -> dict[str, int]:
        definitions = self._collect_builtin_definitions()
        definition_ids = {definition.capability_id for definition in definitions}
        ts = now_utc()
        installed = 0
        updated = 0
        restored = 0
        retired = 0

        with get_db() as conn:
            self._sync_source_registrations(conn, ts)
            rows = conn.execute("SELECT * FROM capability_records").fetchall()
            existing = {row["capability_id"]: row for row in rows}
            builtin_rows = [
                row for row in rows
                if row["source_kind"] == "builtin_pack"
            ]

            for definition in definitions:
                row = existing.get(definition.capability_id)
                if (
                    row is not None
                    and row["source_kind"] != "builtin_pack"
                    and row["lifecycle_state"] == "installed"
                ):
                    continue

                snapshot = self._snapshot_from_definition(definition)
                created_at = row["created_at"] if row is not None else ts
                if row is None:
                    event_type = "installed"
                    installed += 1
                else:
                    previous = self._snapshot_from_row(row)
                    if row["lifecycle_state"] != "installed":
                        event_type = "restored"
                        restored += 1
                    elif previous != snapshot:
                        event_type = "updated"
                        updated += 1
                    else:
                        event_type = None

                package_object_id = row["package_object_id"] if row is not None else None
                if event_type is not None or not package_object_id:
                    package_object_id = self._insert_package_object(
                        conn,
                        capability_id=definition.capability_id,
                        version=definition.version,
                        package_kind="builtin_capability_package",
                        source_kind="builtin_pack",
                        source_ref=definition.pack_id,
                        snapshot_data=snapshot,
                        created_at=ts,
                    )
                self._upsert_capability_record(
                    conn,
                    definition=definition,
                    package_object_id=package_object_id,
                    source_kind="builtin_pack",
                    source_ref=definition.pack_id,
                    created_at=created_at,
                    updated_at=ts,
                )
                if event_type is not None:
                    self._insert_record_event(
                        conn,
                        capability_id=definition.capability_id,
                        event_type=event_type,
                        source_kind="builtin_pack",
                        source_ref=definition.pack_id,
                        snapshot_data=snapshot,
                        created_at=ts,
                    )

            for row in builtin_rows:
                capability_id = row["capability_id"]
                if capability_id in definition_ids or row["lifecycle_state"] == "retired":
                    continue
                conn.execute(
                    """
                    UPDATE capability_records
                    SET lifecycle_state='retired', updated_at=?
                    WHERE capability_id=?
                    """,
                    (ts, capability_id),
                )
                retired += 1
                self._insert_record_event(
                    conn,
                    capability_id=capability_id,
                    event_type="retired",
                    source_kind=row["source_kind"],
                    source_ref=row["source_ref"],
                    snapshot_data=self._snapshot_from_row(row),
                    created_at=ts,
                )

            conn.commit()

        return {
            "installed": installed,
            "updated": updated,
            "restored": restored,
            "retired": retired,
            "total_live": self.count_installed_capabilities(),
        }

    def count_builtin_records(self) -> int:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM capability_records WHERE source_kind = 'builtin_pack'"
            ).fetchone()
        return int(row[0] or 0)

    def count_installed_capabilities(self) -> int:
        self.ensure_builtin_catalog()
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM capability_records WHERE lifecycle_state = 'installed'"
            ).fetchone()
        return int(row[0] or 0)

    def list_installed_records(self) -> list[CapabilityRecord]:
        self.ensure_builtin_catalog()
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM capability_records
                WHERE lifecycle_state = 'installed'
                ORDER BY capability_id ASC
                """
            ).fetchall()
            if self._ensure_package_objects_for_rows(conn, rows):
                rows = conn.execute(
                    """
                    SELECT *
                    FROM capability_records
                    WHERE lifecycle_state = 'installed'
                    ORDER BY capability_id ASC
                    """
                ).fetchall()
        return [CapabilityRecord.from_row(row) for row in rows]

    def list_installed_capability_ids(self) -> list[str]:
        return [record.capability_id for record in self.list_installed_records()]

    def list_installed_inventory_entries(self) -> list[dict[str, Any]]:
        return [record.to_inventory_dict() for record in self.list_installed_records()]

    def hydrate_registry(self, registry: CapabilityRegistry) -> int:
        """Project the durable installed catalog into an eager runtime registry.

        Function capabilities are registered before composites so registry-level
        validation can resolve component references deterministically.
        """
        records = self.list_installed_records()
        definitions = [
            record.to_definition(resolve_binding_ref=self.resolve_binding_ref)
            for record in records
        ]
        functions = [
            definition
            for definition in definitions
            if definition.capability_type == "function"
        ]
        composites = [
            definition
            for definition in definitions
            if definition.capability_type == "composite"
        ]
        for definition in functions:
            registry.register(definition)

        pending = composites
        while pending:
            deferred: list[CapabilityDefinition] = []
            for definition in pending:
                component_ids = (
                    definition.combination.component_capabilities
                    if definition.combination is not None
                    else ()
                )
                if all(component_id in registry.list_ids() for component_id in component_ids):
                    registry.register(definition)
                else:
                    deferred.append(definition)
            if len(deferred) == len(pending):
                unresolved = ", ".join(
                    definition.capability_id for definition in deferred
                )
                raise ValueError(
                    "Stored composite capabilities have unresolved component "
                    f"dependencies: {unresolved}"
                )
            pending = deferred

        return len(definitions)

    def get_installed_record(self, capability_id: str) -> CapabilityRecord | None:
        self.ensure_builtin_catalog()
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM capability_records
                WHERE capability_id = ? AND lifecycle_state = 'installed'
                """,
                (capability_id,),
            ).fetchone()
            if row is not None and self._ensure_package_objects_for_rows(conn, [row]):
                row = conn.execute(
                    """
                    SELECT *
                    FROM capability_records
                    WHERE capability_id = ? AND lifecycle_state = 'installed'
                    """,
                    (capability_id,),
                ).fetchone()
        return CapabilityRecord.from_row(row) if row else None

    def get_installed_record_or_raise(self, capability_id: str) -> CapabilityRecord:
        record = self.get_installed_record(capability_id)
        if record is None:
            raise CapabilityRecordNotFoundError(
                f"Installed capability record not found: {capability_id!r}"
            )
        return record

    def list_record_events(
        self,
        capability_id: str,
    ) -> list[CapabilityRecordEvent]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM capability_record_events
                WHERE capability_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (capability_id,),
            ).fetchall()
        return [CapabilityRecordEvent.from_row(row) for row in rows]

    def get_package_object(self, package_object_id: str) -> CapabilityPackageObject | None:
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM capability_package_objects
                WHERE id = ?
                """,
                (package_object_id,),
            ).fetchone()
        return CapabilityPackageObject.from_row(row) if row else None

    def get_package_object_or_raise(self, package_object_id: str) -> CapabilityPackageObject:
        package_object = self.get_package_object(package_object_id)
        if package_object is None:
            raise CapabilityRecordNotFoundError(
                f"Capability package object not found: {package_object_id!r}"
            )
        return package_object

    def get_installed_capability_detail(self, capability_id: str) -> dict[str, Any]:
        record = self.get_installed_record_or_raise(capability_id)
        package_object = (
            self.get_package_object(record.package_object_id)
            if record.package_object_id
            else None
        )
        events = self.list_record_events(capability_id)
        return {
            **record.to_inventory_dict(),
            "implementation_ref": record.implementation_ref,
            "combination_logic_ref": record.combination_logic_ref,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "package_object": package_object.to_dict() if package_object is not None else None,
            "record_events": [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "source_kind": event.source_kind,
                    "source_ref": event.source_ref,
                    "created_at": event.created_at,
                    "snapshot_data": event.snapshot_data,
                }
                for event in events
            ],
        }

    def build_draft_seed_from_installed_capability(self, capability_id: str) -> dict[str, Any]:
        record = self.get_installed_record_or_raise(capability_id)
        package_object = (
            self.get_package_object(record.package_object_id)
            if record.package_object_id
            else None
        )
        snapshot = (
            dict(package_object.snapshot_data)
            if package_object is not None
            else self._snapshot_from_record(record)
        )
        snapshot_capability_id = snapshot["capability_id"]
        capability_type = snapshot.get("capability_type", "function") or "function"
        # Normalize legacy type names that may exist in old package object snapshots
        if capability_type == "base":
            capability_type = "function"
        elif capability_type == "combination":
            capability_type = "composite"
        draft_data: dict[str, Any] = {
            "capability_id": snapshot_capability_id,
            "display_name": snapshot.get("display_name", "") or "",
            "description": snapshot.get("description", "") or "",
            "capability_type": capability_type,
            "pack_id": snapshot.get("pack_id", "") or "",
            "version": snapshot.get("version", "1") or "1",
            "icon": snapshot.get("icon"),
            "tags": list(snapshot.get("tags", [])),
            "contract": {
                "inputs": list(snapshot.get("contract", {}).get("inputs", [])),
                "output": list(snapshot.get("contract", {}).get("output", [])),
                "constraints": list(snapshot.get("contract", {}).get("constraints", [])),
            },
            "implementation_ref": snapshot.get("implementation_ref"),
            "combination_logic_ref": snapshot.get("combination_logic_ref"),
            "derived_from_capability_id": record.capability_id,
            "derived_from_package_object_id": record.package_object_id,
            "derived_from_source_kind": record.source_kind,
            "derived_from_source_ref": record.source_ref,
            "execution_source": snapshot.get("execution_source", "binding_ref") or "binding_ref",
            "code_block": snapshot.get("code_block", "") or "",
            "entrypoint": snapshot.get("entrypoint") or "run",
            "publish_outputs": list(snapshot.get("publish_outputs") or ["python_artifact", "text_summary"]),
        }
        if capability_type == "function":
            draft_data["implementation_logic"] = None
        if capability_type == "composite":
            draft_data["component_capabilities"] = list(snapshot.get("component_capabilities", []))
            draft_data["execution_order"] = list(snapshot.get("execution_order", []))

        return {
            "draft_name": (
                f"{snapshot.get('display_name') or snapshot_capability_id} (draft copy)"
            ),
            "draft_description": snapshot.get("description", "") or "",
            "planned_capability_id": snapshot_capability_id,
            "draft_data": draft_data,
        }

    def install_published_draft_items(
        self,
        *,
        conn,
        draft,
        items,
        history_id: str,
    ) -> dict[str, int]:
        ts = now_utc()
        installed = 0
        replaced = 0
        seen_ids: set[str] = set()

        for item in items:
            snapshot = self._snapshot_from_published_draft_item(
                draft=draft,
                item=item,
                history_id=history_id,
            )
            capability_id = snapshot["capability_id"]
            if capability_id in seen_ids:
                raise ValueError(
                    f"Duplicate capability_id in publish batch: {capability_id!r}"
                )
            seen_ids.add(capability_id)

            row = conn.execute(
                "SELECT * FROM capability_records WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
            created_at = row["created_at"] if row is not None else ts
            event_type = "installed_from_draft_publication" if row is None else "replaced_from_draft_publication"
            package_object_id = self._insert_package_object(
                conn,
                capability_id=snapshot["capability_id"],
                version=snapshot["version"],
                package_kind="draft_publication_package",
                source_kind="draft_publication",
                source_ref=history_id,
                snapshot_data=snapshot,
                created_at=ts,
            )

            # Determine execution_source for this publication.
            # User-authored capabilities default to 'code_block' (execute from stored source).
            # Explicitly provided values in draft_data are respected.
            publish_execution_source = snapshot.get("execution_source") or "code_block"
            publish_entrypoint = snapshot.get("entrypoint") or "run"
            publish_outputs = snapshot.get("publish_outputs") or ["python_artifact", "text_summary"]

            conn.execute(
                """
                INSERT INTO capability_records (
                    capability_id,
                    package_object_id,
                    pack_id,
                    version,
                    display_name,
                    description,
                    lifecycle_state,
                    capability_type,
                    contract_json,
                    tags_json,
                    icon,
                    implementation_ref,
                    combination_logic_ref,
                    component_capabilities_json,
                    execution_order_json,
                    source_kind,
                    source_ref,
                    code_block,
                    execution_source,
                    entrypoint,
                    publish_outputs_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                    package_object_id=excluded.package_object_id,
                    pack_id=excluded.pack_id,
                    version=excluded.version,
                    display_name=excluded.display_name,
                    description=excluded.description,
                    lifecycle_state='installed',
                    capability_type=excluded.capability_type,
                    contract_json=excluded.contract_json,
                    tags_json=excluded.tags_json,
                    icon=excluded.icon,
                    implementation_ref=excluded.implementation_ref,
                    combination_logic_ref=excluded.combination_logic_ref,
                    component_capabilities_json=excluded.component_capabilities_json,
                    execution_order_json=excluded.execution_order_json,
                    source_kind=excluded.source_kind,
                    source_ref=excluded.source_ref,
                    code_block=excluded.code_block,
                    execution_source=excluded.execution_source,
                    entrypoint=excluded.entrypoint,
                    publish_outputs_json=excluded.publish_outputs_json,
                    updated_at=excluded.updated_at
                """,
                (
                    snapshot["capability_id"],
                    package_object_id,
                    snapshot["pack_id"],
                    snapshot["version"],
                    snapshot["display_name"],
                    snapshot["description"],
                    "installed",
                    snapshot["capability_type"],
                    json.dumps(snapshot["contract"], sort_keys=True),
                    json.dumps(snapshot["tags"], sort_keys=True),
                    snapshot["icon"],
                    snapshot["implementation_ref"],
                    snapshot["combination_logic_ref"],
                    json.dumps(snapshot["component_capabilities"], sort_keys=True),
                    json.dumps(snapshot["execution_order"], sort_keys=True),
                    "draft_publication",
                    history_id,
                    snapshot.get("code_block", ""),
                    publish_execution_source,
                    publish_entrypoint,
                    json.dumps(publish_outputs, sort_keys=False),
                    created_at,
                    ts,
                ),
            )
            # Stamp published_forms onto the snapshot before writing the event ledger
            # so history records reflect exactly which forms existed at this publication.
            event_snapshot = dict(snapshot)
            event_snapshot["published_forms"] = publish_outputs
            event_snapshot["entrypoint"] = publish_entrypoint
            event_id = str(uuid.uuid4())
            self._insert_record_event(
                conn,
                capability_id=capability_id,
                event_type=event_type,
                source_kind="draft_publication",
                source_ref=history_id,
                snapshot_data=event_snapshot,
                created_at=ts,
                event_id=event_id,
            )

            # Generate package-owned published artifact files and register in DB index.
            code_block = snapshot.get("code_block", "")
            for form_kind in publish_outputs:
                artifact_path = ""
                try:
                    if form_kind == "python_artifact" and code_block:
                        written = write_published_python(capability_id, code_block)
                        invalidate_published_python_cache(capability_id)
                        artifact_path = str(written)
                    elif form_kind == "json_snapshot":
                        import json as _json
                        content = _json.dumps(event_snapshot, indent=2, sort_keys=True)
                        written = write_published_json(capability_id, content)
                        artifact_path = str(written)
                    elif form_kind == "text_summary":
                        content = build_text_summary(event_snapshot)
                        written = write_published_text(capability_id, content)
                        artifact_path = str(written)
                    else:
                        # Unknown form kind — skip
                        continue
                except Exception:
                    # Artifact write failure is non-fatal for catalog install;
                    # the capability record is already committed.
                    artifact_path = ""
                conn.execute(
                    """
                    INSERT INTO capability_published_forms (
                        id, capability_id, form_kind, artifact_path, publish_event_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), capability_id, form_kind, artifact_path, event_id, ts),
                )

            if row is None:
                installed += 1
            else:
                replaced += 1

        if seen_ids:
            conn.execute(
                """
                UPDATE capability_publication_candidates
                SET publication_state='installed'
                WHERE history_id = ?
                """,
                (history_id,),
            )
            # Register the publication source so it is visible in the source registry
            conn.execute(
                """
                INSERT INTO capability_source_registrations
                    (source_ref, source_kind, module_path, display_name, is_active,
                     registered_at, updated_at)
                VALUES (?, 'draft_publication', '', ?, 1, ?, ?)
                ON CONFLICT(source_ref) DO UPDATE SET
                    is_active  = 1,
                    updated_at = excluded.updated_at
                """,
                (history_id, f"draft_publication:{history_id[:8]}", ts, ts),
            )

        return {
            "installed_live_count": installed,
            "replaced_live_count": replaced,
        }

    def resolve_binding_ref(self, binding_ref: str) -> Any:
        module_name, _, qualname = binding_ref.partition(":")
        if not module_name or not qualname:
            raise ValueError(f"Invalid capability binding ref: {binding_ref!r}")
        obj: Any = importlib.import_module(module_name)
        for part in qualname.split("."):
            obj = getattr(obj, part)
        if not callable(obj):
            raise TypeError(f"Resolved binding ref is not callable: {binding_ref!r}")
        return obj

    def binding_ref_for_callable(self, value: Any) -> str | None:
        if value is None:
            return None
        module_name = getattr(value, "__module__", "")
        qualname = getattr(value, "__qualname__", "")
        if not module_name or not qualname or "<locals>" in qualname:
            raise ValueError(
                f"Capability catalog requires importable top-level callables, got {value!r}"
            )
        return f"{module_name}:{qualname}"

    def _collect_builtin_definitions(self) -> list[CapabilityDefinition]:
        """
        Collect all CapabilityDefinition objects from active builtin pack sources.

        Uses BUILTIN_CAPABILITY_PACK_REGISTRARS as the bootstrap seed AND reads
        active capability_source_registrations rows with source_kind='builtin_pack'
        to discover any additionally registered packs.  Sources in both places are
        deduplicated by module_path.
        """
        import importlib

        registry = CapabilityRegistry()

        # Seed set: module_paths already loaded from the hardcoded tuple
        loaded_paths: set[str] = set()
        for module_name, register_fn in BUILTIN_CAPABILITY_PACK_REGISTRARS:
            register_fn(registry)
            loaded_paths.add(module_name)

        # DB-registered extra sources (added via register_source())
        try:
            with get_db() as conn:
                extra_rows = conn.execute(
                    """
                    SELECT module_path FROM capability_source_registrations
                    WHERE source_kind = 'builtin_pack' AND is_active = 1
                    """
                ).fetchall()
        except Exception:
            extra_rows = []

        for row in extra_rows:
            module_path = row["module_path"]
            if module_path in loaded_paths:
                continue
            try:
                mod = importlib.import_module(module_path)
                if hasattr(mod, "register") and callable(mod.register):
                    mod.register(registry)
                    loaded_paths.add(module_path)
            except Exception:
                pass  # Unloadable extra pack — silently skip, don't break startup

        return registry.snapshot()

    def _upsert_capability_record(
        self,
        conn,
        *,
        definition: CapabilityDefinition,
        package_object_id: str,
        source_kind: str,
        source_ref: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        contract_json = json.dumps(
            {
                "inputs": list(definition.contract.inputs),
                "output": list(definition.contract.output),
                "constraints": list(definition.contract.constraints),
            },
            sort_keys=True,
        )
        tags_json = json.dumps(list(definition.tags), sort_keys=True)
        component_capabilities_json = json.dumps(
            list(definition.combination.component_capabilities)
            if definition.combination is not None
            else [],
            sort_keys=True,
        )
        execution_order_json = json.dumps(
            list(definition.combination.execution_order)
            if definition.combination is not None
            else [],
            sort_keys=True,
        )
        conn.execute(
            """
            INSERT INTO capability_records (
                capability_id,
                package_object_id,
                pack_id,
                version,
                display_name,
                description,
                lifecycle_state,
                capability_type,
                contract_json,
                tags_json,
                icon,
                implementation_ref,
                combination_logic_ref,
                component_capabilities_json,
                execution_order_json,
                source_kind,
                source_ref,
                code_block,
                execution_source,
                entrypoint,
                publish_outputs_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(capability_id) DO UPDATE SET
                package_object_id=excluded.package_object_id,
                pack_id=excluded.pack_id,
                version=excluded.version,
                display_name=excluded.display_name,
                description=excluded.description,
                lifecycle_state='installed',
                capability_type=excluded.capability_type,
                contract_json=excluded.contract_json,
                tags_json=excluded.tags_json,
                icon=excluded.icon,
                implementation_ref=excluded.implementation_ref,
                combination_logic_ref=excluded.combination_logic_ref,
                component_capabilities_json=excluded.component_capabilities_json,
                execution_order_json=excluded.execution_order_json,
                source_kind=excluded.source_kind,
                source_ref=excluded.source_ref,
                code_block=CASE WHEN capability_records.code_block = '' THEN excluded.code_block ELSE capability_records.code_block END,
                updated_at=excluded.updated_at
            """,
            (
                definition.capability_id,
                package_object_id,
                definition.pack_id,
                definition.version,
                definition.display_name,
                definition.description,
                "installed",
                definition.capability_type,
                contract_json,
                tags_json,
                definition.icon,
                self.binding_ref_for_callable(definition.implementation_logic),
                self.binding_ref_for_callable(
                    definition.combination.combination_logic
                    if definition.combination is not None
                    else None
                ),
                component_capabilities_json,
                execution_order_json,
                source_kind,
                source_ref,
                self._code_block_for_definition(definition),
                "binding_ref",
                "run",
                json.dumps(["python_artifact", "text_summary"]),
                created_at,
                updated_at,
            ),
        )

    def _insert_record_event(
        self,
        conn,
        *,
        capability_id: str,
        event_type: str,
        source_kind: str,
        source_ref: str,
        snapshot_data: dict[str, Any],
        created_at: str,
        event_id: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO capability_record_events (
                id,
                capability_id,
                event_type,
                source_kind,
                source_ref,
                snapshot_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id or str(uuid.uuid4()),
                capability_id,
                event_type,
                source_kind,
                source_ref,
                json.dumps(snapshot_data, sort_keys=True),
                created_at,
            ),
        )

    def _insert_package_object(
        self,
        conn,
        *,
        capability_id: str,
        version: str,
        package_kind: str,
        source_kind: str,
        source_ref: str,
        snapshot_data: dict[str, Any],
        created_at: str,
    ) -> str:
        package_object_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO capability_package_objects (
                id,
                capability_id,
                version,
                package_kind,
                source_kind,
                source_ref,
                snapshot_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                package_object_id,
                capability_id,
                version,
                package_kind,
                source_kind,
                source_ref,
                json.dumps(snapshot_data, sort_keys=True),
                created_at,
            ),
        )
        return package_object_id

    def _snapshot_from_definition(self, definition: CapabilityDefinition) -> dict[str, Any]:
        return {
            "capability_id": definition.capability_id,
            "pack_id": definition.pack_id,
            "version": definition.version,
            "display_name": definition.display_name,
            "description": definition.description,
            "capability_type": definition.capability_type,
            "contract": {
                "inputs": list(definition.contract.inputs),
                "output": list(definition.contract.output),
                "constraints": list(definition.contract.constraints),
            },
            "tags": list(definition.tags),
            "icon": definition.icon,
            "implementation_ref": self.binding_ref_for_callable(definition.implementation_logic),
            "combination_logic_ref": self.binding_ref_for_callable(
                definition.combination.combination_logic
                if definition.combination is not None
                else None
            ),
            "component_capabilities": (
                list(definition.combination.component_capabilities)
                if definition.combination is not None
                else []
            ),
            "execution_order": (
                list(definition.combination.execution_order)
                if definition.combination is not None
                else []
            ),
            "source_kind": "builtin_pack",
            "source_ref": definition.pack_id,
            "code_block": self._code_block_for_definition(definition),
            # Builtins use binding_ref: bootstrap-regime exception (source lives in Python module).
            # Same package model applies; only execution_source differs from authored capabilities.
            "execution_source": "binding_ref",
            "entrypoint": "run",
            "publish_outputs": ["python_artifact", "text_summary"],
        }

    def _code_block_for_definition(self, definition: CapabilityDefinition) -> str:
        """
        Return the canonical code_block string for a CapabilityDefinition.

        Prefers definition.capability_module_text when provided (full self-contained
        module text); falls back to inspect.getsource on the implementation_logic
        callable.
        """
        if definition.capability_module_text is not None:
            return definition.capability_module_text
        return self._source_for_callable(definition.implementation_logic)

    def _source_for_callable(self, fn: Any) -> str:
        if fn is None:
            return ""
        try:
            return inspect.getsource(fn)
        except (OSError, TypeError):
            return ""

    def _sync_source_registrations(self, conn, ts: str) -> None:
        """
        Write one capability_source_registrations row per entry in
        BUILTIN_CAPABILITY_PACK_REGISTRARS.  Any existing builtin row not in
        the current constant is deactivated (is_active=0).

        Must be called inside an open connection context from _run_builtin_sync().
        """
        active_source_refs = {module_name for module_name, _ in BUILTIN_CAPABILITY_PACK_REGISTRARS}
        for module_name, _ in BUILTIN_CAPABILITY_PACK_REGISTRARS:
            conn.execute(
                """
                INSERT INTO capability_source_registrations
                    (source_ref, source_kind, module_path, display_name, is_active,
                     registered_at, updated_at)
                VALUES (?, 'builtin_pack', ?, ?, 1, ?, ?)
                ON CONFLICT(source_ref) DO UPDATE SET
                    is_active   = 1,
                    updated_at  = excluded.updated_at
                """,
                (module_name, module_name, module_name, ts, ts),
            )
        # Deactivate removed builtin sources
        conn.execute(
            f"""
            UPDATE capability_source_registrations
            SET is_active = 0, updated_at = ?
            WHERE source_kind = 'builtin_pack'
              AND source_ref NOT IN ({','.join('?' * len(active_source_refs))})
              AND is_active = 1
            """,
            (ts, *active_source_refs),
        )

    def upsert_draft_publication_source_registration(
        self, history_id: str, ts: str | None = None
    ) -> None:
        """
        Write a capability_source_registrations row for a draft publication event.

        Called by install_published_draft_items() so that published draft sources
        are visible in the source registry while the system is off.
        """
        ts = ts or now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO capability_source_registrations
                    (source_ref, source_kind, module_path, display_name, is_active,
                     registered_at, updated_at)
                VALUES (?, 'draft_publication', '', ?, 1, ?, ?)
                ON CONFLICT(source_ref) DO UPDATE SET
                    is_active  = 1,
                    updated_at = excluded.updated_at
                """,
                (history_id, f"draft_publication:{history_id[:8]}", ts, ts),
            )
            conn.commit()

    def list_source_registrations(self) -> list[dict[str, Any]]:
        """Return all capability_source_registrations rows as dicts."""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM capability_source_registrations ORDER BY source_kind ASC, source_ref ASC"
            ).fetchall()
        return [
            {
                "source_ref": row["source_ref"],
                "source_kind": row["source_kind"],
                "module_path": row["module_path"],
                "display_name": row["display_name"],
                "is_active": bool(row["is_active"]),
                "registered_at": row["registered_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def register_source(
        self,
        module_path: str,
        *,
        display_name: str | None = None,
        source_kind: str = "builtin_pack",
    ) -> dict[str, Any]:
        """
        Register a new capability pack source in capability_source_registrations.

        The source will be included in the next seed_builtin_catalog() / sync_builtin_catalog()
        call.  If the source_ref already exists, it is re-activated and its display_name
        is updated.

        Returns the upserted source registration dict.
        """
        ts = now_utc()
        source_ref = module_path
        dn = display_name or module_path
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO capability_source_registrations
                    (source_ref, source_kind, module_path, display_name, is_active,
                     registered_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(source_ref) DO UPDATE SET
                    is_active    = 1,
                    display_name = excluded.display_name,
                    updated_at   = excluded.updated_at
                """,
                (source_ref, source_kind, module_path, dn, ts, ts),
            )
            conn.commit()
        return {
            "source_ref": source_ref,
            "source_kind": source_kind,
            "module_path": module_path,
            "display_name": dn,
            "is_active": True,
            "registered_at": ts,
            "updated_at": ts,
        }

    def _snapshot_from_row(self, row) -> dict[str, Any]:
        return {
            "capability_id": row["capability_id"],
            "pack_id": row["pack_id"],
            "version": row["version"],
            "display_name": row["display_name"],
            "description": row["description"],
            "capability_type": row["capability_type"],
            "contract": json.loads(row["contract_json"] or "{}"),
            "tags": list(json.loads(row["tags_json"] or "[]")),
            "icon": row["icon"],
            "implementation_ref": row["implementation_ref"],
            "combination_logic_ref": row["combination_logic_ref"],
            "component_capabilities": list(
                json.loads(row["component_capabilities_json"] or "[]")
            ),
            "execution_order": list(json.loads(row["execution_order_json"] or "[]")),
            "source_kind": row["source_kind"],
            "source_ref": row["source_ref"],
            "code_block": row["code_block"] if row["code_block"] is not None else "",
            "execution_source": row["execution_source"] if row["execution_source"] is not None else "binding_ref",
            "entrypoint": (row["entrypoint"] if row["entrypoint"] is not None else "run")
                if "entrypoint" in (row.keys() if hasattr(row, "keys") else []) else "run",
            "publish_outputs": (
                json.loads(row["publish_outputs_json"]) if row["publish_outputs_json"] else ["python_artifact", "text_summary"]
            ) if "publish_outputs_json" in (row.keys() if hasattr(row, "keys") else []) else ["python_artifact", "text_summary"],
        }

    def _snapshot_from_record(self, record: CapabilityRecord) -> dict[str, Any]:
        return {
            "capability_id": record.capability_id,
            "pack_id": record.pack_id,
            "version": record.version,
            "display_name": record.display_name,
            "description": record.description,
            "capability_type": record.capability_type,
            "contract": {
                "inputs": list(record.contract.get("inputs", [])),
                "output": list(record.contract.get("output", [])),
                "constraints": list(record.contract.get("constraints", [])),
            },
            "tags": list(record.tags),
            "icon": record.icon,
            "implementation_ref": record.implementation_ref,
            "combination_logic_ref": record.combination_logic_ref,
            "component_capabilities": list(record.component_capabilities),
            "execution_order": list(record.execution_order),
            "source_kind": record.source_kind,
            "source_ref": record.source_ref,
            "code_block": record.code_block if record.code_block is not None else "",
            "execution_source": record.execution_source if record.execution_source else "binding_ref",
            "entrypoint": record.entrypoint if record.entrypoint else "run",
            "publish_outputs": list(record.publish_outputs) if record.publish_outputs else ["python_artifact", "text_summary"],
        }

    def _ensure_package_objects_for_rows(self, conn, rows) -> bool:
        changed = False
        for row in rows:
            if row["package_object_id"]:
                continue
            snapshot = self._snapshot_from_row(row)
            package_object_id = self._insert_package_object(
                conn,
                capability_id=row["capability_id"],
                version=row["version"],
                package_kind="installed_capability_snapshot",
                source_kind=row["source_kind"],
                source_ref=row["source_ref"],
                snapshot_data=snapshot,
                created_at=row["updated_at"],
            )
            conn.execute(
                """
                UPDATE capability_records
                SET package_object_id = ?
                WHERE capability_id = ?
                """,
                (package_object_id, row["capability_id"]),
            )
            changed = True
        if changed:
            conn.commit()
        return changed

    def _snapshot_from_published_draft_item(
        self,
        *,
        draft,
        item,
        history_id: str,
    ) -> dict[str, Any]:
        draft_data = dict(item.draft_data)
        capability_id = draft_data.get("capability_id") or item.planned_capability_id
        capability_type = draft_data.get("capability_type", "function")
        # Normalize legacy type names from pre-rename snapshots
        if capability_type == "base":
            capability_type = "function"
        elif capability_type == "combination":
            capability_type = "composite"
        combination_logic_ref = draft_data.get("combination_logic_ref")
        if not combination_logic_ref and capability_type == "composite":
            logic_kind = draft_data.get("combination_logic_kind", "merge")
            combination_logic_ref = binding_ref_for_combination_logic_kind(logic_kind)

        return {
            "capability_id": capability_id,
            "pack_id": draft_data.get("pack_id", f"draft.{draft.id[:8]}"),
            "version": draft_data.get("version", draft.version),
            "display_name": draft_data.get("display_name", capability_id),
            "description": draft_data.get("description", ""),
            "capability_type": capability_type,
            "contract": draft_data.get(
                "contract",
                {"inputs": [], "output": [], "constraints": []},
            ),
            "tags": list(draft_data.get("tags", [])),
            "icon": draft_data.get("icon"),
            "implementation_ref": draft_data.get("implementation_ref"),
            "combination_logic_ref": combination_logic_ref,
            "component_capabilities": list(draft_data.get("component_capabilities", [])),
            "execution_order": list(draft_data.get("execution_order", [])),
            "source_kind": "draft_publication",
            "source_ref": history_id,
            "code_block": draft_data.get("code_block", ""),
            "execution_source": draft_data.get("execution_source", "binding_ref"),
            "entrypoint": draft_data.get("entrypoint") or "run",
            "publish_outputs": draft_data.get("publish_outputs") or ["python_artifact", "text_summary"],
        }


__all__ = [
    "BUILTIN_CAPABILITY_PACK_REGISTRARS",
    "CapabilityCatalogService",
    "CapabilityRecordNotFoundError",
]
