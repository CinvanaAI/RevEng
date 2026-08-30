from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

from reveng.analysis_engine.coordination.orchestrator import run as orchestrator_run
from reveng.storage.db_connection import init_db
from reveng.platform.services.capability_catalog_service import CapabilityCatalogService
from reveng.platform.web.routers.capability_environment import platform_inventory
from reveng.storage.system_db import ensure_system_db_ready
from reveng.storage.framework_logs import (
    list_framework_logs_for_run,
)


class FrameworkLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = Path(__file__).resolve().parent / "_framework_logging"
        shutil.rmtree(cls.workspace, ignore_errors=True)
        cls.workspace.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def setUp(self) -> None:
        init_db(self.workspace / "_framework_logging_reset.db")
        self.repo_dir = self.workspace / "repo"
        self.output_dir = self.workspace / "output"
        self.db_path = self.workspace / f"{self._testMethodName}.db"
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.repo_dir / "main.py").write_text(
            "from helper import run\n\n"
            "def main():\n"
            "    return run()\n",
            encoding="utf-8",
        )
        (self.repo_dir / "helper.py").write_text(
            "def run():\n"
            "    return {'ok': True}\n",
            encoding="utf-8",
        )
        self._old_db_env = os.environ.get("REVENG_DB")
        os.environ["REVENG_DB"] = str(self.db_path)
        ensure_system_db_ready(self.db_path)

    def tearDown(self) -> None:
        init_db(self.workspace / "_framework_logging_reset.db")
        if self._old_db_env is None:
            os.environ.pop("REVENG_DB", None)
        else:
            os.environ["REVENG_DB"] = self._old_db_env
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_orchestrator_run_persists_framework_logs(self) -> None:
        run_id = "framework-log-run"
        result = orchestrator_run(
            inputs={
                "repo_path": str(self.repo_dir),
                "with_ai": False,
                "layered": False,
                "extractor_workers": 1,
                "ai_file_workers": 1,
                "env_file": ".env",
            },
            output_dir=str(self.output_dir),
            run_id=run_id,
        )
        self.assertEqual("ok", result["status"])

        logs = list_framework_logs_for_run(run_id)
        self.assertGreater(len(logs), 0)
        self.assertTrue(all(log.run_id == run_id for log in logs))

        event_types = {log.event_type for log in logs}
        origins = {log.origin for log in logs}
        self.assertIn("coordination.host_composition", origins)
        self.assertIn("platform.capability_registry", origins)
        self.assertIn("framework.workflow_registry", origins)
        self.assertIn("framework.host", origins)
        self.assertIn("framework.runtime", origins)
        self.assertIn("default_host_build_started", event_types)
        self.assertIn("capability_registered", event_types)
        self.assertIn("workflow_registered", event_types)
        self.assertIn("workflow_runtime_initialized", event_types)
        self.assertIn("capability_invocation_completed", event_types)
        self.assertIn("workflow_execution_completed", event_types)
        self.assertIn("artifact_recorded", event_types)
        self.assertTrue(
            any(
                log.event_type == "permission_check_missing"
                and log.boundary_sensitive
                and log.architectural_drift_detected
                for log in logs
            )
        )

    def test_platform_inventory_reads_from_storage_backed_catalog(self) -> None:
        inventory = platform_inventory(catalog=CapabilityCatalogService())
        self.assertEqual(52, inventory["installed_count"])


if __name__ == "__main__":
    unittest.main()
