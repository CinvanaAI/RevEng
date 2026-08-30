from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

from reveng.storage.db_connection import get_db
from reveng.platform.services.agent_capability_access_service import (
    AgentCapabilityAccessService,
)
from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.agent_service import AgentInactiveError, AgentService
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
from reveng.platform.services.analysis_bridge import submit_analysis_run
from reveng.platform.services.capability_catalog_service import CapabilityCatalogService
from reveng.platform.services.event_service import EventService
from reveng.platform.services.output_service import OutputService
from reveng.platform.services.run_service import RunService
from reveng.platform.utils import now_utc
from reveng.storage.framework_logs import list_framework_logs_for_run
from reveng.storage.system_db import ensure_system_db_ready


class _InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


class AgentToolPermissionTests(unittest.TestCase):
    REQUIRED_BASE_WORKFLOW_CAPABILITIES = [
        "python.scan_repo",
        "python.extract_file",
        "python.inventory.assemble",
        "python.relations.build",
        "python.file_breakdowns.build",
        "python.file_breakdowns.enrich",
        "python.clusters.build",
        "python.flows.build",
        "report.repo_dossier.build",
        "report.validate",
        "report.unknowns.build",
    ]

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = Path(__file__).resolve().parent / "_agent_tool_permissions"
        shutil.rmtree(cls.workspace, ignore_errors=True)
        cls.workspace.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def setUp(self) -> None:
        self.db_path = self.workspace / f"{self._testMethodName}.db"
        self.repo_dir = self.workspace / f"{self._testMethodName}_repo"
        self.output_dir = self.workspace / f"{self._testMethodName}_out"
        self.db_path.unlink(missing_ok=True)
        (self.workspace / f"{self._testMethodName}.db-shm").unlink(missing_ok=True)
        (self.workspace / f"{self._testMethodName}.db-wal").unlink(missing_ok=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._old_db_env = os.environ.get("REVENG_DB")
        os.environ["REVENG_DB"] = str(self.db_path)

        ensure_system_db_ready(self.db_path)
        self.catalog = CapabilityCatalogService()
        self.catalog.sync_builtin_catalog()
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO providers
                    (id, kind, label, base_url, api_key_env, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "permission-provider",
                    "openai",
                    "Permission Provider",
                    "https://example.invalid/v1",
                    "OPENAI_API_KEY",
                    1,
                    ts,
                    ts,
                ),
            )
            conn.commit()
        self.agent_service = AgentService()
        self.tool_file_permissions = AgentToolFilePermissionService(
            agent_service=self.agent_service,
        )
        self.keycards = AgentKeycardService(
            agent_service=self.agent_service,
            tool_file_permission_service=self.tool_file_permissions,
        )
        self.access = AgentCapabilityAccessService(
            agent_service=self.agent_service,
            keycard_service=self.keycards,
            tool_file_permission_service=self.tool_file_permissions,
            capability_catalog=self.catalog,
        )
        self.run_service = RunService()
        self.event_service = EventService()
        self.output_service = OutputService()

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

    def tearDown(self) -> None:
        if self._old_db_env is None:
            os.environ.pop("REVENG_DB", None)
        else:
            os.environ["REVENG_DB"] = self._old_db_env
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def _create_active_agent(self, name: str):
        agent = self.agent_service.create(
            name=name,
            description=f"{name} description",
            provider_id="permission-provider",
            model="gpt-4o-mini",
        )
        self.agent_service.set_active(agent.id, True)
        return agent

    def _assign_repo_keycard(self, agent_id: str) -> list[str]:
        assignments = self.keycards.assign_files(
            agent_id,
            root_path=self.repo_dir,
            absolute_paths=[
                self.repo_dir / "main.py",
                self.repo_dir / "helper.py",
            ],
        )
        for assignment in assignments:
            self.keycards.set_global_eligibility(
                agent_id,
                assignment.absolute_path,
                enabled=True,
            )
        return [assignment.absolute_path for assignment in assignments]

    def test_runtime_permission_check_tracks_grant_and_revoke(self) -> None:
        agent = self._create_active_agent("Permission Agent")
        allowed_paths = self._assign_repo_keycard(agent.id)

        self.assertFalse(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.scan_repo",
                inputs={"visible_file_paths": allowed_paths},
            )
        )

        self.access.grant_tool_to_agent(agent.id, "python.scan_repo")
        self.assertTrue(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.scan_repo",
                inputs={"visible_file_paths": allowed_paths},
            )
        )

        self.access.revoke_tool_from_agent(agent.id, "python.scan_repo")
        self.assertFalse(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.scan_repo",
                inputs={"visible_file_paths": allowed_paths},
            )
        )

    def test_submit_analysis_run_fails_without_granted_capabilities(self) -> None:
        agent = self._create_active_agent("Denied Agent")
        self._assign_repo_keycard(agent.id)

        run_id = submit_analysis_run(
            executor=_InlineExecutor(),
            repo_path=str(self.repo_dir),
            output_dir=str(self.output_dir),
            with_ai=False,
            layered=False,
            ai_limit=None,
            extractor_workers=1,
            ai_file_workers=1,
            env_file=".env",
            run_service=self.run_service,
            event_service=self.event_service,
            output_service=self.output_service,
            agent_service=self.agent_service,
            agent_capability_access_service=self.access,
            agent_keycard_service=self.keycards,
            provider_service=None,
            agent_id=agent.id,
        )

        record = self.run_service.get_or_raise(run_id)
        self.assertEqual("failed", record.status)
        self.assertIn("Permission denied for capability", record.error_message or "")
        self.assertIsNone(self.agent_service.get_spec(agent.id).current_state.current_run_id)

        framework_logs = list_framework_logs_for_run(run_id)
        self.assertTrue(
            any(log.event_type == "permission_check_denied" for log in framework_logs)
        )

    def test_submit_analysis_run_rejects_inactive_agent_before_runtime(self) -> None:
        agent = self.agent_service.create(
            name="Inactive Agent",
            description="Inactive agent",
            provider_id="permission-provider",
            model="gpt-4o-mini",
        )
        self._assign_repo_keycard(agent.id)
        for capability_id in self.REQUIRED_BASE_WORKFLOW_CAPABILITIES:
            self.access.grant_tool_to_agent(agent.id, capability_id)

        with self.assertRaises(AgentInactiveError):
            submit_analysis_run(
                executor=_InlineExecutor(),
                repo_path=str(self.repo_dir),
                output_dir=str(self.output_dir),
                with_ai=False,
                layered=False,
                ai_limit=None,
                extractor_workers=1,
                ai_file_workers=1,
                env_file=".env",
                run_service=self.run_service,
                event_service=self.event_service,
                output_service=self.output_service,
                agent_service=self.agent_service,
                agent_capability_access_service=self.access,
                agent_keycard_service=self.keycards,
                provider_service=None,
                agent_id=agent.id,
            )

    def test_inactive_agent_is_denied_by_permission_policy_even_with_grant(self) -> None:
        agent = self.agent_service.create(
            name="Inactive Permission Agent",
            description="Inactive permission agent",
            provider_id="permission-provider",
            model="gpt-4o-mini",
        )
        allowed_paths = self._assign_repo_keycard(agent.id)
        self.access.grant_tool_to_agent(agent.id, "python.scan_repo")

        self.assertFalse(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.scan_repo",
                inputs={"visible_file_paths": allowed_paths},
            )
        )
        permission_check = self.access.build_runtime_permission_check(agent.id)
        self.assertFalse(
            permission_check(
                "python.scan_repo",
                {"visible_file_paths": allowed_paths},
            )
        )

    def test_unavailable_granted_capability_is_denied_and_exposed_as_unavailable(self) -> None:
        agent = self._create_active_agent("Unavailable Capability Agent")
        allowed_paths = self._assign_repo_keycard(agent.id)
        self.access.grant_tool_to_agent(agent.id, "python.scan_repo")

        with get_db() as conn:
            conn.execute(
                """
                UPDATE capability_records
                SET lifecycle_state = 'retired'
                WHERE capability_id = 'python.scan_repo'
                """
            )
            conn.commit()

        self.assertFalse(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.scan_repo",
                inputs={"visible_file_paths": allowed_paths},
            )
        )
        state = self.access.get_assignment_state(agent.id)
        self.assertEqual(["python.scan_repo"], state["assigned_capability_ids"])
        self.assertFalse(state["assigned_installed_tools"])
        self.assertEqual(
            "python.scan_repo",
            state["unavailable_assignments"][0]["capability_id"],
        )

    def test_runtime_denies_extract_file_when_global_or_tool_file_permission_is_cleared(self) -> None:
        agent = self._create_active_agent("Scoped File Agent")
        allowed_paths = self._assign_repo_keycard(agent.id)
        target_path = str((self.repo_dir / "main.py").resolve())
        self.access.grant_tool_to_agent(agent.id, "python.extract_file")

        self.assertTrue(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.extract_file",
                inputs={
                    "repo_root": str(self.repo_dir),
                    "file_path": target_path,
                    "allowed_file_paths": allowed_paths,
                },
            )
        )

        self.tool_file_permissions.set_allowed(
            agent.id,
            "python.extract_file",
            target_path,
            allowed=False,
        )
        self.assertFalse(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.extract_file",
                inputs={
                    "repo_root": str(self.repo_dir),
                    "file_path": target_path,
                    "allowed_file_paths": allowed_paths,
                },
            )
        )

        self.keycards.set_global_eligibility(agent.id, target_path, enabled=False)
        self.assertFalse(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.extract_file",
                inputs={
                    "repo_root": str(self.repo_dir),
                    "file_path": target_path,
                    "allowed_file_paths": allowed_paths,
                },
            )
        )

    def test_runtime_denies_when_keycard_file_is_removed(self) -> None:
        agent = self._create_active_agent("Removed File Agent")
        self._assign_repo_keycard(agent.id)
        target_path = str((self.repo_dir / "helper.py").resolve())
        self.access.grant_tool_to_agent(agent.id, "python.extract_file")

        self.assertTrue(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.extract_file",
                inputs={
                    "repo_root": str(self.repo_dir),
                    "file_path": target_path,
                    "allowed_file_paths": [target_path],
                },
            )
        )

        self.keycards.remove_file(agent.id, target_path)
        self.assertFalse(
            self.access.is_capability_allowed_for_agent(
                agent.id,
                "python.extract_file",
                inputs={
                    "repo_root": str(self.repo_dir),
                    "file_path": target_path,
                    "allowed_file_paths": [target_path],
                },
            )
        )

    def test_submit_analysis_run_stays_blind_without_keycard_files(self) -> None:
        agent = self._create_active_agent("Blind Agent")
        for capability_id in self.REQUIRED_BASE_WORKFLOW_CAPABILITIES:
            self.access.grant_tool_to_agent(agent.id, capability_id)

        run_id = submit_analysis_run(
            executor=_InlineExecutor(),
            repo_path=str(self.repo_dir),
            output_dir=str(self.output_dir),
            with_ai=False,
            layered=False,
            ai_limit=None,
            extractor_workers=1,
            ai_file_workers=1,
            env_file=".env",
            run_service=self.run_service,
            event_service=self.event_service,
            output_service=self.output_service,
            agent_service=self.agent_service,
            agent_capability_access_service=self.access,
            agent_keycard_service=self.keycards,
            provider_service=None,
            agent_id=agent.id,
        )

        record = self.run_service.get_or_raise(run_id)
        self.assertEqual("completed", record.status)
        outputs = {output.output_key: output.value for output in self.output_service.get_outputs_for_run(run_id)}
        self.assertEqual("0", outputs["file_count"])

    def test_submit_analysis_run_completes_once_required_tools_are_granted(self) -> None:
        agent = self._create_active_agent("Allowed Agent")
        self._assign_repo_keycard(agent.id)
        for capability_id in self.REQUIRED_BASE_WORKFLOW_CAPABILITIES:
            self.access.grant_tool_to_agent(agent.id, capability_id)

        run_id = submit_analysis_run(
            executor=_InlineExecutor(),
            repo_path=str(self.repo_dir),
            output_dir=str(self.output_dir),
            with_ai=False,
            layered=False,
            ai_limit=None,
            extractor_workers=1,
            ai_file_workers=1,
            env_file=".env",
            run_service=self.run_service,
            event_service=self.event_service,
            output_service=self.output_service,
            agent_service=self.agent_service,
            agent_capability_access_service=self.access,
            agent_keycard_service=self.keycards,
            provider_service=None,
            agent_id=agent.id,
        )

        record = self.run_service.get_or_raise(run_id)
        self.assertEqual("completed", record.status)
        self.assertIsNone(record.error_message)
        self.assertGreater(len(self.output_service.get_outputs_for_run(run_id)), 0)

        framework_logs = list_framework_logs_for_run(run_id)
        self.assertTrue(
            any(log.event_type == "permission_check_allowed" for log in framework_logs)
        )
        self.assertFalse(
            any(log.event_type == "permission_check_denied" for log in framework_logs)
        )


if __name__ == "__main__":
    unittest.main()
