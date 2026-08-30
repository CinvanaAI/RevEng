from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from reveng.coordination.execution import MAX_PARALLEL_WORKERS, bounded_worker_count
from reveng.framework.cache import ExistsAndNonEmptyCachePolicy
from reveng.framework.runtime import WorkflowRuntime
from reveng.framework.trusted_code import AUTHORED_CODE_ENV
from reveng.platform.capabilities import CapabilityRegistry
from reveng.platform.models.capability_record import _make_code_block_callable
from reveng.platform.services.filesystem_explorer_service import FilesystemExplorerService
from reveng.platform.web.app import create_app


class WebRequestBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = Path(__file__).resolve().parent / "_web_request_boundary"
        shutil.rmtree(cls.workspace, ignore_errors=True)
        cls.workspace.mkdir(parents=True, exist_ok=True)
        cls._old_db_env = os.environ.get("REVENG_DB")
        os.environ["REVENG_DB"] = str(cls.workspace / "platform.db")
        cls.client_context = TestClient(create_app())
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        if cls._old_db_env is None:
            os.environ.pop("REVENG_DB", None)
        else:
            os.environ["REVENG_DB"] = cls._old_db_env
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def test_rejects_nonlocal_host_header(self) -> None:
        response = self.client.get("/", headers={"Host": "attacker.example"})
        self.assertEqual(403, response.status_code)

    def test_rejects_cross_origin_form_post(self) -> None:
        response = self.client.post(
            "/capabilities/settings",
            data={"selected_skin_id": "random"},
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(403, response.status_code)

    def test_rejects_cross_site_fetch_metadata(self) -> None:
        response = self.client.post(
            "/capabilities/settings",
            data={"selected_skin_id": "random"},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(403, response.status_code)

    def test_allows_same_origin_form_post(self) -> None:
        response = self.client.post(
            "/capabilities/settings",
            data={"selected_skin_id": "random"},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )
        self.assertEqual(303, response.status_code)


class RuntimeBoundaryTests(unittest.TestCase):
    def test_missing_permission_check_denies_before_capability_lookup(self) -> None:
        runtime = WorkflowRuntime(
            capability_registry=CapabilityRegistry(),
            output_dir=Path(__file__).resolve().parent,
            run_id="missing-permission-check",
            workflow_id="test.workflow",
            cache=ExistsAndNonEmptyCachePolicy(),
        )
        with self.assertRaisesRegex(PermissionError, "Permission check missing"):
            runtime.invoke("does.not.exist", {})

    def test_authored_capability_code_is_disabled_by_default(self) -> None:
        code = "def run(context):\n    return {'ok': True}\n"
        with patch.dict(os.environ, {AUTHORED_CODE_ENV: ""}):
            with self.assertRaisesRegex(PermissionError, AUTHORED_CODE_ENV):
                _make_code_block_callable(code, "test.authored")

    def test_authored_capability_code_requires_explicit_opt_in(self) -> None:
        code = "def run(context):\n    return {'ok': True}\n"
        with patch.dict(os.environ, {AUTHORED_CODE_ENV: "1"}):
            implementation = _make_code_block_callable(code, "test.authored")
        self.assertEqual({"ok": True}, implementation(None))

    def test_parallel_worker_count_is_capped(self) -> None:
        self.assertEqual(
            MAX_PARALLEL_WORKERS,
            bounded_worker_count(10_000, 10_000),
        )


class FilesystemBoundaryTests(unittest.TestCase):
    def test_requested_root_outside_allowlist_falls_back(self) -> None:
        workspace = Path(__file__).resolve().parent / "_filesystem_boundary"
        trusted = workspace / "trusted"
        outside = workspace / "outside"
        shutil.rmtree(workspace, ignore_errors=True)
        trusted.mkdir(parents=True)
        outside.mkdir(parents=True)
        (trusted / "allowed.py").write_text("pass\n", encoding="utf-8")
        (outside / "private.txt").write_text("private\n", encoding="utf-8")
        try:
            result = FilesystemExplorerService().list_directory(
                root_path=outside,
                allowed_roots=[trusted],
            )
            self.assertEqual(str(trusted.resolve()), result["root_path"])
            self.assertEqual(
                ["allowed.py"],
                [entry["name"] for entry in result["entries"]],
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
