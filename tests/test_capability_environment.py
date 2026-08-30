from __future__ import annotations

import os
import shutil
import sqlite3
import unittest
from pathlib import Path

from reveng.coordination.host_composition import build_default_host
from reveng.storage.db_connection import init_db
from reveng.storage.db_migrations import apply_migrations
from reveng.storage.db_connection import get_db
from reveng.platform.services.capability_catalog_service import CapabilityCatalogService
from reveng.platform.services.draft_service import CapabilityDraftService
from reveng.platform.utils import now_utc
from reveng.platform.web.routers.capability_environment import platform_inventory


class CapabilityEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = Path(__file__).resolve().parent / "_capability_environment"
        shutil.rmtree(cls.workspace, ignore_errors=True)
        cls.workspace.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def setUp(self) -> None:
        self.db_path = self.workspace / f"{self._testMethodName}.db"
        self._old_db_env = os.environ.get("REVENG_DB")
        os.environ["REVENG_DB"] = str(self.db_path)
        init_db(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        apply_migrations(conn)
        conn.close()
        self.draft_svc = CapabilityDraftService()

    def tearDown(self) -> None:
        init_db(self.workspace / "_reset.db")
        if self._old_db_env is None:
            os.environ.pop("REVENG_DB", None)
        else:
            os.environ["REVENG_DB"] = self._old_db_env
        self.db_path.unlink(missing_ok=True)
        Path(f"{self.db_path}-shm").unlink(missing_ok=True)
        Path(f"{self.db_path}-wal").unlink(missing_ok=True)

    def test_platform_inventory_exposes_capability_object_shape(self) -> None:
        inventory = platform_inventory(catalog=CapabilityCatalogService())
        self.assertEqual(52, inventory["installed_count"])
        self.assertGreater(len(inventory["capabilities"]), 0)
        sample = inventory["capabilities"][0]
        self.assertIn("contract", sample)
        self.assertIn("version", sample)
        self.assertIn("icon", sample)
        self.assertIn("package_object_id", sample)
        self.assertIn("has_implementation_logic", sample)
        self.assertIn("component_capabilities", sample)
        self.assertIn("execution_order", sample)
        self.assertIn("has_combination_logic", sample)

    def test_platform_inventory_is_backed_by_stored_capability_records(self) -> None:
        inventory = platform_inventory(catalog=CapabilityCatalogService())
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM capability_records
                WHERE lifecycle_state = 'installed'
                """
            ).fetchone()
        self.assertEqual(inventory["installed_count"], row[0])
        self.assertEqual(52, row[0])

    def test_default_host_hydrates_from_stored_capability_catalog(self) -> None:
        platform_inventory(catalog=CapabilityCatalogService())
        with get_db() as conn:
            conn.execute(
                "DELETE FROM capability_records WHERE capability_id = ?",
                ("python.scan_repo",),
            )
            conn.commit()
        try:
            host = build_default_host()
            capability_ids = set(host.capabilities.list_ids())
            self.assertEqual(51, len(capability_ids))
            self.assertNotIn("python.scan_repo", capability_ids)
        finally:
            CapabilityCatalogService().sync_builtin_catalog()

    def test_installed_capability_detail_and_draft_seed_use_platform_package_object(self) -> None:
        catalog = CapabilityCatalogService()
        detail = catalog.get_installed_capability_detail("python.scan_repo")
        seed = catalog.build_draft_seed_from_installed_capability("python.scan_repo")

        self.assertEqual("python.scan_repo", detail["capability_id"])
        self.assertIsNotNone(detail["package_object"])
        self.assertEqual("python.scan_repo", detail["package_object"]["capability_id"])
        self.assertEqual(
            detail["package_object"]["id"],
            detail["package_object_id"],
        )
        self.assertEqual("python.scan_repo", seed["planned_capability_id"])
        self.assertEqual(
            detail["package_object"]["id"],
            seed["draft_data"]["derived_from_package_object_id"],
        )
        self.assertEqual(
            "python.scan_repo",
            seed["draft_data"]["derived_from_capability_id"],
        )

    def test_draft_validation_accepts_same_draft_combination(self) -> None:
        draft = self.draft_svc.create_draft(name="Combination Validation Draft")
        self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.base_a",
            draft_data={
                "capability_id": "test.base_a",
                "display_name": "Base A",
                "description": "",
                "capability_type": "base",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
            },
        )
        self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.combo_collect",
            draft_data={
                "capability_id": "test.combo_collect",
                "display_name": "Collect Combo",
                "description": "",
                "capability_type": "combination",
                "component_capabilities": ["test.base_a"],
                "execution_order": ["test.base_a"],
                "combination_logic_kind": "collect",
                "contract": {"inputs": [], "output": [], "constraints": []},
            },
        )

        report = self.draft_svc.validate_draft(draft.id)
        self.assertEqual(2, report["passed"])
        self.assertEqual(0, report["failed"])
        self.assertEqual(draft.id, report["draft_id"])

    def test_export_includes_combination_spec(self) -> None:
        draft = self.draft_svc.create_draft(name="Combination Export Draft")
        self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.base_b",
            draft_data={
                "capability_id": "test.base_b",
                "display_name": "Base B",
                "description": "",
                "capability_type": "base",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
            },
        )
        self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.combo_merge",
            draft_data={
                "capability_id": "test.combo_merge",
                "display_name": "Merge Combo",
                "description": "",
                "capability_type": "combination",
                "component_capabilities": ["test.base_b"],
                "execution_order": ["test.base_b"],
                "combination_logic_kind": "merge",
                "contract": {"inputs": [], "output": [], "constraints": []},
            },
        )
        report = self.draft_svc.validate_draft(draft.id)
        self.assertEqual(2, report["passed"])

        snippet = self.draft_svc.export_draft_as_pack_snippet(draft.id)
        self.assertIn("CombinationSpec(", snippet)
        self.assertIn("combination_logic=_combination_logic('merge')", snippet)

    def test_validation_rejects_base_item_without_implementation_ref(self) -> None:
        draft = self.draft_svc.create_draft(name="Validation Requires Binding Draft")
        item = self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.unbound_base",
            draft_data={
                "capability_id": "test.unbound_base",
                "display_name": "Unbound Base",
                "description": "",
                "capability_type": "base",
                "contract": {"inputs": [], "output": [], "constraints": []},
            },
        )

        report = self.draft_svc.validate_draft(draft.id)

        self.assertEqual(0, report["passed"])
        self.assertEqual(1, report["failed"])
        self.assertIn("implementation_ref", report["results"][0]["violations"][0])
        refreshed = self.draft_svc.get_draft_item_or_raise(item.id)
        self.assertEqual("draft", refreshed.item_state)

    def test_validation_rejects_unresolvable_implementation_ref(self) -> None:
        draft = self.draft_svc.create_draft(name="Validation Requires Resolvable Binding Draft")
        item = self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.bad_binding",
            draft_data={
                "capability_id": "test.bad_binding",
                "display_name": "Bad Binding",
                "description": "",
                "capability_type": "base",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:not_a_real_callable",
            },
        )

        report = self.draft_svc.validate_draft(draft.id)

        self.assertEqual(0, report["passed"])
        self.assertEqual(1, report["failed"])
        self.assertTrue(
            any("could not be resolved for publish" in violation for violation in report["results"][0]["violations"])
        )
        refreshed = self.draft_svc.get_draft_item_or_raise(item.id)
        self.assertEqual("draft", refreshed.item_state)

    def test_validation_rejects_duplicate_live_capability_ids_in_publish_batch(self) -> None:
        draft = self.draft_svc.create_draft(name="Duplicate Publish IDs Draft")
        for planned_capability_id in ("test.duplicate_one", "test.duplicate_two"):
            self.draft_svc.add_draft_item(
                draft.id,
                planned_capability_id=planned_capability_id,
                draft_data={
                    "capability_id": "test.shared_live_id",
                    "display_name": "Shared Live ID",
                    "description": "",
                    "capability_type": "base",
                    "contract": {"inputs": [], "output": [], "constraints": []},
                    "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
                },
            )

        report = self.draft_svc.validate_draft(draft.id)

        self.assertEqual(0, report["passed"])
        self.assertEqual(2, report["failed"])
        for result in report["results"]:
            self.assertTrue(any("duplicates another draft item" in violation for violation in result["violations"]))

    def test_publish_accepts_combination_without_explicit_logic_kind_by_defaulting_merge(self) -> None:
        draft = self.draft_svc.create_draft(name="Default Combination Logic Draft")
        self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.combo_base",
            draft_data={
                "capability_id": "test.combo_base",
                "display_name": "Combination Base",
                "description": "",
                "capability_type": "base",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
            },
        )
        self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.combo_default_merge",
            draft_data={
                "capability_id": "test.combo_default_merge",
                "display_name": "Default Merge Combination",
                "description": "",
                "capability_type": "combination",
                "component_capabilities": ["test.combo_base"],
                "execution_order": ["test.combo_base"],
                "contract": {"inputs": [], "output": [], "constraints": []},
            },
        )

        report = self.draft_svc.validate_draft(draft.id)
        self.assertEqual(2, report["passed"])

        result = self.draft_svc.publish_draft(draft.id)
        self.assertTrue(result["ok"])
        self.assertEqual(2, result["installed_live_count"])

    def test_publish_rejects_validated_item_with_unresolvable_binding(self) -> None:
        draft = self.draft_svc.create_draft(name="Publish Rejects Unresolvable Binding Draft")
        item = self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.bad_publish_binding",
            draft_data={
                "capability_id": "test.bad_publish_binding",
                "display_name": "Bad Publish Binding",
                "description": "",
                "capability_type": "base",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:not_a_real_callable",
            },
        )

        with get_db() as conn:
            conn.execute(
                "UPDATE capability_draft_items SET item_state='validated' WHERE id=?",
                (item.id,),
            )
            conn.commit()

        result = self.draft_svc.publish_draft(draft.id)
        self.assertFalse(result["ok"])
        self.assertIn("executable-ready", result["error"])
        self.assertEqual(["test.bad_publish_binding"], result["non_installable_capability_ids"])

    def test_save_draft_version_records_snapshot_and_advances_current_version(self) -> None:
        draft = self.draft_svc.create_draft(
            name="Workbench Revision Draft",
            description="Used to verify saved workbench versions.",
        )
        item = self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.versioned_capability",
            draft_data={
                "capability_id": "test.versioned_capability",
                "display_name": "Versioned Capability",
                "description": "Draft item for revision snapshot testing.",
                "capability_type": "base",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "version": "1.0.0",
            },
        )

        revision = self.draft_svc.save_draft_version(draft.id, version="1.1.0")
        updated = self.draft_svc.get_draft_or_raise(draft.id)
        history = self.draft_svc.get_draft_revision_history(draft.id)

        self.assertEqual("1.1.0", revision.version)
        self.assertEqual("1.1.0", updated.version)
        self.assertEqual(1, len(history))
        self.assertEqual(revision.id, history[0].id)
        self.assertEqual(draft.id, revision.snapshot_data["draft"]["id"])
        self.assertEqual("1.1.0", revision.snapshot_data["draft"]["version"])
        self.assertEqual("1.0.0", revision.snapshot_data["items"][0]["draft_data"]["version"])
        self.assertEqual(item.id, revision.snapshot_data["items"][0]["id"])

    def test_publish_records_platform_publication_candidates(self) -> None:
        draft = self.draft_svc.create_draft(name="Publish Candidate Draft")
        self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.publish_ready",
            draft_data={
                "capability_id": "test.publish_ready",
                "display_name": "Publish Ready Capability",
                "description": "",
                "capability_type": "base",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
            },
        )

        report = self.draft_svc.validate_draft(draft.id)
        self.assertEqual(1, report["passed"])

        result = self.draft_svc.publish_draft(draft.id)
        self.assertTrue(result["ok"])
        self.assertEqual(1, result["publication_candidate_count"])
        self.assertEqual(1, result["executable_candidate_count"])
        self.assertEqual(1, result["installed_live_count"])
        self.assertEqual(0, result["replaced_live_count"])

        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM capability_publication_candidates
                WHERE draft_id = ?
                """,
                (draft.id,),
            ).fetchall()
            installed_row = conn.execute(
                """
                SELECT *
                FROM capability_records
                WHERE capability_id = ?
                """,
                ("test.publish_ready",),
            ).fetchone()
        self.assertEqual(1, len(rows))
        self.assertEqual(result["history_id"], rows[0]["history_id"])
        self.assertEqual("test.publish_ready", rows[0]["capability_id"])
        self.assertEqual(1, rows[0]["executable_ready"])
        self.assertEqual("installed", rows[0]["publication_state"])
        self.assertEqual("draft_publication", installed_row["source_kind"])
        self.assertEqual(result["history_id"], installed_row["source_ref"])
        self.assertTrue(installed_row["package_object_id"])

        host = build_default_host()
        self.assertIn("test.publish_ready", set(host.capabilities.list_ids()))

    def test_rollback_from_saved_revision_republishes_previous_known_good_snapshot(self) -> None:
        catalog = CapabilityCatalogService()
        draft = self.draft_svc.create_draft(name="Revision Rollback Draft")
        item = self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.rollback_revision",
            draft_data={
                "capability_id": "test.rollback_revision",
                "display_name": "Rollback Revision V1",
                "description": "First known-good revision.",
                "capability_type": "base",
                "version": "1.0.0",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
            },
        )
        revision = self.draft_svc.save_draft_version(draft.id, version="1.1.0")

        self.draft_svc.update_draft_item(
            item.id,
            draft_data={
                "capability_id": "test.rollback_revision",
                "display_name": "Rollback Revision V2",
                "description": "Current live version before rollback.",
                "capability_type": "base",
                "version": "2.0.0",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
            },
        )
        report = self.draft_svc.validate_draft(draft.id)
        self.assertEqual(1, report["passed"])
        publish_result = self.draft_svc.publish_draft(draft.id)
        self.assertTrue(publish_result["ok"])
        self.assertEqual(
            "Rollback Revision V2",
            catalog.get_installed_record_or_raise("test.rollback_revision").display_name,
        )

        rollback_result = self.draft_svc.rollback_draft_to_revision(draft.id, revision.id)
        self.assertTrue(rollback_result["ok"])
        self.assertTrue(rollback_result["rollback_draft_id"])

        rollback_draft = self.draft_svc.get_draft_or_raise(rollback_result["rollback_draft_id"])
        self.assertEqual("published", rollback_draft.lifecycle_state)
        restored = catalog.get_installed_record_or_raise("test.rollback_revision")
        self.assertEqual("Rollback Revision V1", restored.display_name)
        self.assertEqual("1.0.0", restored.version)
        self.assertEqual("draft_publication", restored.source_kind)

    def test_rollback_from_publication_history_republishes_previous_published_snapshot(self) -> None:
        catalog = CapabilityCatalogService()
        draft = self.draft_svc.create_draft(name="Publication Rollback Draft")
        item = self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="test.rollback_publication",
            draft_data={
                "capability_id": "test.rollback_publication",
                "display_name": "Publication Rollback V1",
                "description": "First published version.",
                "capability_type": "base",
                "version": "1.0.0",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
            },
        )
        report = self.draft_svc.validate_draft(draft.id)
        self.assertEqual(1, report["passed"])
        first_publish = self.draft_svc.publish_draft(draft.id)
        self.assertTrue(first_publish["ok"])

        self.draft_svc.update_draft_item(
            item.id,
            draft_data={
                "capability_id": "test.rollback_publication",
                "display_name": "Publication Rollback V2",
                "description": "Second published version.",
                "capability_type": "base",
                "version": "2.0.0",
                "contract": {"inputs": [], "output": [], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
            },
        )
        report = self.draft_svc.validate_draft(draft.id)
        self.assertEqual(1, report["passed"])
        second_publish = self.draft_svc.publish_draft(draft.id)
        self.assertTrue(second_publish["ok"])
        self.assertEqual(
            "Publication Rollback V2",
            catalog.get_installed_record_or_raise("test.rollback_publication").display_name,
        )

        rollback_result = self.draft_svc.rollback_draft_to_publication(
            draft.id,
            first_publish["history_id"],
        )
        self.assertTrue(rollback_result["ok"])
        rollback_draft = self.draft_svc.get_draft_or_raise(rollback_result["rollback_draft_id"])
        self.assertEqual("published", rollback_draft.lifecycle_state)

        restored = catalog.get_installed_record_or_raise("test.rollback_publication")
        self.assertEqual("Publication Rollback V1", restored.display_name)
        self.assertEqual("1.0.0", restored.version)
        self.assertEqual("draft_publication", restored.source_kind)

    def test_publish_can_replace_live_installed_capability_and_survive_builtin_sync(self) -> None:
        platform_inventory(catalog=CapabilityCatalogService())
        catalog = CapabilityCatalogService()
        original = catalog.get_installed_record_or_raise("python.scan_repo")

        draft = self.draft_svc.create_draft(name="Replace Installed Capability Draft")
        self.draft_svc.add_draft_item(
            draft.id,
            planned_capability_id="python.scan_repo",
            draft_data={
                "capability_id": "python.scan_repo",
                "display_name": "Scan Python Repository Override",
                "description": "Overrides the installed scan capability through publish.",
                "capability_type": "base",
                "pack_id": "draft.override",
                "version": "99.0.0",
                "contract": {"inputs": ["repo_path"], "output": ["scan_result"], "constraints": []},
                "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
            },
        )

        report = self.draft_svc.validate_draft(draft.id)
        self.assertEqual(1, report["passed"])

        result = self.draft_svc.publish_draft(draft.id)
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["installed_live_count"])
        self.assertEqual(1, result["replaced_live_count"])

        try:
            replaced = catalog.get_installed_record_or_raise("python.scan_repo")
            self.assertEqual("99.0.0", replaced.version)
            self.assertEqual("draft_publication", replaced.source_kind)
            self.assertEqual(result["history_id"], replaced.source_ref)

            catalog.sync_builtin_catalog()
            after_sync = catalog.get_installed_record_or_raise("python.scan_repo")
            self.assertEqual("99.0.0", after_sync.version)
            self.assertEqual("draft_publication", after_sync.source_kind)
        finally:
            with get_db() as conn:
                conn.execute(
                    "DELETE FROM capability_records WHERE capability_id = ?",
                    ("python.scan_repo",),
                )
                conn.commit()
            catalog.sync_builtin_catalog()
            restored = catalog.get_installed_record_or_raise("python.scan_repo")
            self.assertEqual(original.version, restored.version)
            self.assertEqual("builtin_pack", restored.source_kind)

    def test_legacy_bundle_storage_migrates_to_draft_tables(self) -> None:
        legacy_db = self.workspace / "legacy_platform.db"
        if legacy_db.exists():
            legacy_db.unlink()

        init_db(legacy_db)
        conn = sqlite3.connect(str(legacy_db))
        try:
            ts = now_utc()
            conn.executescript(
                """
                CREATE TABLE schema_versions (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                INSERT INTO schema_versions (version, applied_at) VALUES (22, '2026-04-03T00:00:00Z');

                CREATE TABLE capability_bundles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    lifecycle_state TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT '1.0.0'
                );
                CREATE INDEX idx_capability_bundles_lifecycle_state
                    ON capability_bundles(lifecycle_state);

                CREATE TABLE capability_draft_items (
                    id TEXT PRIMARY KEY,
                    bundle_id TEXT NOT NULL REFERENCES capability_bundles(id) ON DELETE CASCADE,
                    planned_capability_id TEXT NOT NULL,
                    draft_data TEXT NOT NULL DEFAULT '{}',
                    item_state TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX idx_capability_draft_items_bundle_id
                    ON capability_draft_items(bundle_id);

                CREATE TABLE bundle_publish_history (
                    id TEXT PRIMARY KEY,
                    bundle_id TEXT NOT NULL REFERENCES capability_bundles(id) ON DELETE CASCADE,
                    version TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX idx_bundle_publish_history_bundle_id
                    ON bundle_publish_history(bundle_id);
                """
            )
            conn.execute(
                """
                INSERT INTO capability_bundles
                    (id, name, description, lifecycle_state, created_at, updated_at, version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("legacy-draft", "Legacy Draft", "Migrated from old table names.", "published", ts, ts, "2.0.0"),
            )
            conn.execute(
                """
                INSERT INTO capability_draft_items
                    (id, bundle_id, planned_capability_id, draft_data, item_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("legacy-item", "legacy-draft", "legacy.capability", '{"capability_id":"legacy.capability"}', "published", ts, ts),
            )
            conn.execute(
                """
                INSERT INTO bundle_publish_history
                    (id, bundle_id, version, published_at, item_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("legacy-history", "legacy-draft", "2.0.0", ts, 1),
            )
            conn.commit()

            apply_migrations(conn)
            conn.row_factory = sqlite3.Row

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertIn("capability_drafts", tables)
            self.assertIn("capability_draft_publication_history", tables)
            self.assertNotIn("capability_bundles", tables)
            self.assertNotIn("bundle_publish_history", tables)

            svc = CapabilityDraftService()
            draft = svc.get_draft_or_raise("legacy-draft")
            items = svc.list_draft_items("legacy-draft")
            history = svc.get_draft_publication_history("legacy-draft")
            self.assertEqual("Legacy Draft", draft.name)
            self.assertEqual("legacy.capability", items[0].planned_capability_id)
            self.assertEqual("legacy-draft", history[0].draft_id)
        finally:
            conn.close()
            init_db(self.db_path)


if __name__ == "__main__":
    unittest.main()
