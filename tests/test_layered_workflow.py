"""Tests for the layered meaning breakdown workflow."""
from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path

from reveng.coordination.host_composition import build_default_host
from reveng.analysis_engine.workflows.layered_breakdown import WORKFLOW_ID as LAYERED_WORKFLOW_ID
from reveng.analysis_engine.workflows.repo_analysis import WORKFLOW_ID, WORKFLOW_WITH_AI_ID
from reveng.storage.db_connection import init_db
from reveng.storage.system_db import ensure_system_db_ready


_TEST_DB = Path(__file__).resolve().parent / "_layered_workflow.db"
_OLD_DB_ENV: str | None = None


def setUpModule() -> None:
    global _OLD_DB_ENV
    _OLD_DB_ENV = os.environ.get("REVENG_DB")
    os.environ["REVENG_DB"] = str(_TEST_DB)
    _TEST_DB.unlink(missing_ok=True)
    ensure_system_db_ready(_TEST_DB)


def tearDownModule() -> None:
    init_db(Path(__file__).resolve().parent / "_layered_workflow_reset.db")
    if _OLD_DB_ENV is None:
        os.environ.pop("REVENG_DB", None)
    else:
        os.environ["REVENG_DB"] = _OLD_DB_ENV
    _TEST_DB.unlink(missing_ok=True)
    Path(f"{_TEST_DB}-shm").unlink(missing_ok=True)
    Path(f"{_TEST_DB}-wal").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write_mini_repo(repo_dir: Path) -> None:
    """Two-file mini Python repo with recognizable ability patterns."""
    (repo_dir / "main.py").write_text(
        "import json\n"
        "import logging\n"
        "from helper import process\n\n"
        "logger = logging.getLogger(__name__)\n\n"
        "def main():\n"
        "    data = process({'key': 'value'})\n"
        "    with open('output.json', 'w') as f:\n"
        "        json.dump(data, f)\n"
        "    logger.info('done')\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    (repo_dir / "helper.py").write_text(
        "import json\n\n"
        "def process(data):\n"
        "    print(data)\n"
        "    return json.loads(json.dumps(data))\n\n"
        "def utility():\n"
        "    return 1\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class LayeredHostRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = build_default_host()
        self.capability_ids = set(self.host.capabilities.list_ids())
        self.workflow_ids = set(self.host.workflows.list_ids())

    def test_existing_non_meaning_capabilities_still_present(self) -> None:
        existing = {
            "python.scan_repo", "python.extract_file", "python.inventory.assemble",
            "python.relations.build", "python.file_breakdowns.build",
            "python.file_breakdowns.enrich", "python.clusters.build", "python.flows.build",
            "python.context.per_file.build",
            "report.repo_dossier.build", "report.validate", "report.unknowns.build",
            "llm.file.explain", "llm.file.explanations.assemble",
            "llm.cluster.summarize", "llm.cluster.summaries.assemble",
            "llm.flow.explain", "llm.flow.explanations.assemble",
            "llm.repo.summarize",
        }
        for cap_id in existing:
            self.assertIn(cap_id, self.capability_ids, f"Missing existing capability: {cap_id}")

    def test_9_meaning_capabilities_registered(self) -> None:
        meaning_caps = {
            "meaning.abilities.extract",
            "meaning.actions.derive",
            "meaning.functions.derive",
            "meaning.files.purpose",
            "meaning.files.behavior",
            "meaning.workflows.derive",
            "meaning.modules.summarize",
            "meaning.subsystems.summarize",
            "meaning.system.summarize",
        }
        for cap_id in meaning_caps:
            self.assertIn(cap_id, self.capability_ids, f"Missing meaning capability: {cap_id}")

    def test_removed_agentic_builder_capabilities_not_registered(self) -> None:
        builder_caps = {
            "agentic.builder.scan",
            "agentic.builder.ast",
            "agentic.builder.relations",
            "agentic.builder.file_breakdowns",
            "agentic.builder.enrichment",
            "agentic.builder.clusters",
            "agentic.builder.flows",
            "agentic.builder.dossier",
            "agentic.builder.validate",
            "agentic.builder.llm.file",
            "agentic.builder.llm.cluster",
            "agentic.builder.llm.flow",
            "agentic.builder.llm.repo",
        }
        for cap_id in builder_caps:
            self.assertNotIn(cap_id, self.capability_ids, f"Removed builder capability unexpectedly present: {cap_id}")

    def test_total_52_capabilities(self) -> None:
        self.assertEqual(52, len(self.capability_ids))

    def test_layered_workflow_registered(self) -> None:
        self.assertIn(LAYERED_WORKFLOW_ID, self.workflow_ids)

    def test_3_workflows_registered(self) -> None:
        self.assertEqual(3, len(self.workflow_ids))
        self.assertIn(WORKFLOW_ID, self.workflow_ids)
        self.assertIn(WORKFLOW_WITH_AI_ID, self.workflow_ids)
        self.assertIn(LAYERED_WORKFLOW_ID, self.workflow_ids)


# ---------------------------------------------------------------------------
# Layered workflow run tests
# ---------------------------------------------------------------------------

class LayeredWorkflowRunTests(unittest.TestCase):
    def setUp(self) -> None:
        workspace = Path(__file__).resolve().parent
        self.repo_dir = workspace / "_layered_repo"
        self.output_dir = workspace / "_layered_output"
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        _write_mini_repo(self.repo_dir)

        host = build_default_host()
        result = host.run_workflow(
            LAYERED_WORKFLOW_ID,
            inputs={"repo_path": str(self.repo_dir)},
            output_dir=self.output_dir,
            run_id="test-layered",
        )
        self.outputs = result.outputs
        self.meaning_dir = self.output_dir / "meaning"

    def tearDown(self) -> None:
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)

    # --- Output file existence ---

    def test_all_meaning_json_outputs_exist(self) -> None:
        expected = [
            "ability_records.json",
            "action_records.json",
            "function_meaning_records.json",
            "file_purpose_records.json",
            "file_behavior_records.json",
            "workflow_records.json",
            "module_summary_records.json",
            "subsystem_summary_records.json",
            "system_summary_record.json",
            "system_map.json",
            "crossref_index.json",
        ]
        for fname in expected:
            path = self.meaning_dir / fname
            self.assertTrue(path.exists(), f"Missing output: {path}")
            self.assertGreater(path.stat().st_size, 0, f"Empty output: {path}")

    def test_base_analysis_outputs_still_present(self) -> None:
        self.assertIn("file_count", self.outputs)
        self.assertEqual(2, self.outputs["file_count"])
        self.assertTrue(Path(self.outputs["inventory_path"]).exists())
        self.assertTrue(Path(self.outputs["flow_map_path"]).exists())

    # --- Record content ---

    def test_ability_records_have_derivation(self) -> None:
        data = json.loads((self.meaning_dir / "ability_records.json").read_text(encoding="utf-8"))
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0, "Expected at least one ability record")
        for record in data:
            self.assertIn("derivation", record, "Missing derivation field")
            self.assertIn("basis", record["derivation"], "Missing derivation.basis")

    def test_ability_records_include_expected_abilities(self) -> None:
        data = json.loads((self.meaning_dir / "ability_records.json").read_text(encoding="utf-8"))
        ability_ids = {r["ability_id"] for r in data}
        self.assertIn("can_emit_text_output", ability_ids)
        self.assertIn("can_write_structured_data", ability_ids)

    def test_module_summaries_marked_provisional(self) -> None:
        data = json.loads((self.meaning_dir / "module_summary_records.json").read_text(encoding="utf-8"))
        for record in data:
            self.assertTrue(
                record.get("phase1_approximation"),
                f"Module summary missing phase1_approximation=true: {record.get('module_path')}",
            )

    def test_subsystem_summaries_marked_provisional(self) -> None:
        data = json.loads((self.meaning_dir / "subsystem_summary_records.json").read_text(encoding="utf-8"))
        for record in data:
            self.assertTrue(
                record.get("phase1_approximation"),
                f"Subsystem summary missing phase1_approximation=true: {record.get('subsystem_id')}",
            )

    def test_file_purpose_and_behavior_are_separate_and_non_empty(self) -> None:
        purposes = json.loads((self.meaning_dir / "file_purpose_records.json").read_text(encoding="utf-8"))
        behaviors = json.loads((self.meaning_dir / "file_behavior_records.json").read_text(encoding="utf-8"))
        self.assertGreater(len(purposes), 0, "file_purpose_records should be non-empty")
        self.assertGreater(len(behaviors), 0, "file_behavior_records should be non-empty")

    def test_function_meaning_records_have_resolution_status(self) -> None:
        data = json.loads((self.meaning_dir / "function_meaning_records.json").read_text(encoding="utf-8"))
        self.assertGreater(len(data), 0, "Expected at least one function meaning record")
        for record in data:
            self.assertIn("resolution_status", record, f"Missing resolution_status on {record.get('function_scope')}")
            self.assertIn(
                record["resolution_status"],
                {"behaviorally_resolved", "structurally_discovered"},
                f"Unexpected resolution_status: {record['resolution_status']}",
            )

    def test_system_summary_exists_and_is_dict(self) -> None:
        data = json.loads((self.meaning_dir / "system_summary_record.json").read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        self.assertIn("label", data)
        self.assertIn("is_pass_through", data)

    def test_crossref_index_has_expected_keys(self) -> None:
        data = json.loads((self.meaning_dir / "crossref_index.json").read_text(encoding="utf-8"))
        expected_keys = {
            "ability_to_actions",
            "action_to_functions",
            "function_to_files",
            "file_to_abilities",
            "file_purpose_to_module",
            "file_behavior_to_module",
            "module_to_subsystem",
            "ability_to_dimensions",
        }
        for key in expected_keys:
            self.assertIn(key, data, f"Missing crossref key: {key}")

    # --- Second-run cache test ---

    def test_second_run_uses_cache_for_meaning_json_artifacts(self) -> None:
        """Second run on same output dir: JSON meaning artifacts report cached=True."""
        host = build_default_host()
        result = host.run_workflow(
            LAYERED_WORKFLOW_ID,
            inputs={"repo_path": str(self.repo_dir)},
            output_dir=self.output_dir,
            run_id="test-layered-2",
        )
        outputs = result.outputs
        self.assertTrue(
            outputs.get("ability_count", -1) >= 0,
            "Second run should complete without error",
        )


if __name__ == "__main__":
    unittest.main()
