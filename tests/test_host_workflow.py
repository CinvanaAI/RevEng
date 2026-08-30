from __future__ import annotations

import os
import unittest
from pathlib import Path
import shutil

from reveng.coordination.host_composition import build_default_host
from reveng.framework.permissions import trusted_local_capability_check
from reveng.analysis_engine.workflows.repo_analysis import WORKFLOW_ID, WORKFLOW_WITH_AI_ID
from reveng.storage.db_connection import init_db
from reveng.storage.system_db import ensure_system_db_ready


_TEST_DB = Path(__file__).resolve().parent / "_host_workflow.db"
_OLD_DB_ENV: str | None = None


def setUpModule() -> None:
    global _OLD_DB_ENV
    _OLD_DB_ENV = os.environ.get("REVENG_DB")
    os.environ["REVENG_DB"] = str(_TEST_DB)
    _TEST_DB.unlink(missing_ok=True)
    ensure_system_db_ready(_TEST_DB)


def tearDownModule() -> None:
    init_db(Path(__file__).resolve().parent / "_host_workflow_reset.db")
    if _OLD_DB_ENV is None:
        os.environ.pop("REVENG_DB", None)
    else:
        os.environ["REVENG_DB"] = _OLD_DB_ENV
    _TEST_DB.unlink(missing_ok=True)
    Path(f"{_TEST_DB}-shm").unlink(missing_ok=True)
    Path(f"{_TEST_DB}-wal").unlink(missing_ok=True)


class HostWorkflowTests(unittest.TestCase):
    def test_default_host_registers_capabilities_and_workflows(self) -> None:
        host = build_default_host()

        capability_ids = set(host.capabilities.list_ids())
        workflow_ids = set(host.workflows.list_ids())

        self.assertIn("python.scan_repo", capability_ids)
        self.assertIn("python.relations.build", capability_ids)
        self.assertIn("python.context.per_file.build", capability_ids)
        self.assertIn("report.validate", capability_ids)
        self.assertIn("llm.repo.summarize", capability_ids)
        self.assertIn(WORKFLOW_ID, workflow_ids)
        self.assertIn(WORKFLOW_WITH_AI_ID, workflow_ids)

    def test_default_workflow_runs_through_host(self) -> None:
        host = build_default_host()

        workspace_dir = Path(__file__).resolve().parent
        repo_dir = workspace_dir / "_runtime_repo"
        output_dir = workspace_dir / "_runtime_output"

        shutil.rmtree(repo_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        repo_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            (repo_dir / "main.py").write_text(
                "from helper import run\n\n"
                "def main():\n"
                "    return run()\n\n"
                "if __name__ == '__main__':\n"
                "    main()\n",
                encoding="utf-8",
            )
            (repo_dir / "helper.py").write_text(
                "def run():\n"
                "    return utility()\n\n"
                "def utility():\n"
                "    return 1\n",
                encoding="utf-8",
            )

            result = host.run_workflow(
                WORKFLOW_ID,
                inputs={"repo_path": str(repo_dir)},
                output_dir=output_dir,
                run_id="test-run",
                permission_check=trusted_local_capability_check,
            )

            outputs = result.outputs
            self.assertEqual(2, outputs["file_count"])
            self.assertTrue(Path(outputs["inventory_path"]).exists())
            self.assertTrue(Path(outputs["relation_map_path"]).exists())
            self.assertTrue(Path(outputs["file_breakdowns_path"]).exists())
            self.assertTrue(Path(outputs["enriched_path"]).exists())
            self.assertTrue(Path(outputs["cluster_map_path"]).exists())
            self.assertTrue(Path(outputs["flow_map_path"]).exists())
            self.assertTrue(Path(outputs["repo_dossier_path"]).exists())
            self.assertTrue(Path(outputs["validation_report_path"]).exists())
            self.assertTrue(Path(outputs["unknowns_path"]).exists())
        finally:
            shutil.rmtree(repo_dir, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
