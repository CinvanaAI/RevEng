from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from reveng.storage.db_connection import get_db
from reveng.platform.utils import now_utc
from reveng.platform.web.app import create_app


class AgentEnvironmentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = Path(__file__).resolve().parent / "_agent_environment_ui"
        shutil.rmtree(cls.workspace, ignore_errors=True)
        cls.workspace.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.workspace / "platform.db"
        cls._old_db_env = os.environ.get("REVENG_DB")
        os.environ["REVENG_DB"] = str(cls.db_path)

        cls.client_ctx = TestClient(create_app())
        cls.client = cls.client_ctx.__enter__()

        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO providers
                    (id, kind, label, base_url, api_key_env, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "agent-env-provider",
                    "openai",
                    "Agent Environment Provider",
                    "https://example.invalid/v1",
                    "OPENAI_API_KEY",
                    1,
                    ts,
                    ts,
                ),
            )
            conn.commit()

        cls.seeded_agent = cls.client.app.state.agent_service.create(
            name="Workshop Agent",
            description="The main agent used to verify environment launch flows.",
            provider_id="agent-env-provider",
            model="gpt-4o-mini",
            tool_bindings=["python.scan_repo"],
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_ctx.__exit__(None, None, None)
        if cls._old_db_env is None:
            os.environ.pop("REVENG_DB", None)
        else:
            os.environ["REVENG_DB"] = cls._old_db_env
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def _create_agent(self, *, name: str, tool_bindings: list[str] | None = None):
        return self.client.app.state.agent_service.create(
            name=name,
            description=f"{name} description",
            provider_id="agent-env-provider",
            model="gpt-4o-mini",
            tool_bindings=tool_bindings or [],
        )

    def _tiny_png_bytes(self) -> bytes:
        return (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xdd\x8d\xb1"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    def _assignment_rows_for(self, agent_id: str) -> list[tuple[str, str]]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT capability_id, assignment_state
                FROM agent_capability_assignments
                WHERE agent_id = ?
                ORDER BY capability_id ASC
                """,
                (agent_id,),
            ).fetchall()
        return [(str(row["capability_id"]), str(row["assignment_state"])) for row in rows]

    def _keycard_rows_for(self, agent_id: str) -> list[tuple[str, str, int]]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT absolute_path, visibility_state, global_tool_eligible
                FROM agent_file_assignments
                WHERE agent_id = ?
                ORDER BY absolute_path ASC
                """,
                (agent_id,),
            ).fetchall()
        return [
            (
                str(row["absolute_path"]),
                str(row["visibility_state"]),
                int(row["global_tool_eligible"]),
            )
            for row in rows
        ]

    def _tool_file_rows_for(self, agent_id: str, capability_id: str) -> list[tuple[str, str]]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT absolute_path, permission_state
                FROM agent_tool_file_permissions
                WHERE agent_id = ? AND capability_id = ?
                ORDER BY absolute_path ASC
                """,
                (agent_id, capability_id),
            ).fetchall()
        return [
            (str(row["absolute_path"]), str(row["permission_state"]))
            for row in rows
        ]

    def _create_repo_tree(self, name: str) -> tuple[Path, Path, Path]:
        repo_dir = self.workspace / f"{name}_repo"
        shutil.rmtree(repo_dir, ignore_errors=True)
        repo_dir.mkdir(parents=True, exist_ok=True)
        main_path = repo_dir / "main.py"
        helper_path = repo_dir / "helper.py"
        main_path.write_text("from helper import run\n", encoding="utf-8")
        helper_path.write_text("def run():\n    return True\n", encoding="utf-8")
        return repo_dir, main_path.resolve(), helper_path.resolve()

    def test_sidebar_and_agent_detail_expose_agent_environment_entry(self) -> None:
        agents_response = self.client.get("/agents")
        self.assertEqual(200, agents_response.status_code)
        self.assertIn("Agent Environment", agents_response.text)
        self.assertIn("/agent-environment", agents_response.text)

        detail_response = self.client.get(f"/agents/{self.seeded_agent.id}")
        self.assertEqual(200, detail_response.status_code)
        self.assertIn("Agent Environment", detail_response.text)
        self.assertIn("Open Tools Station", detail_response.text)
        self.assertIn(
            f"/agent-environment/agents/{self.seeded_agent.id}",
            detail_response.text,
        )

    def test_agent_environment_hall_renders_real_agent_roster(self) -> None:
        hall_agent = self._create_agent(name="Hall Agent")
        expected_featured = sorted(
            self.client.app.state.agent_service.list_all(),
            key=lambda agent: (agent.name.casefold(), agent.id),
        )[0]
        redirect = self.client.get("/agent-environment", follow_redirects=False)
        self.assertEqual(303, redirect.status_code)
        self.assertIn("/agent-environment?", redirect.headers["location"])
        self.assertIn(f"agent={expected_featured.id}", redirect.headers["location"])

        response = self.client.get(redirect.headers["location"])
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Skynet Chamber Hall", body)
        self.assertIn("Enter Chamber", body)
        self.assertIn("Jump List", body)
        self.assertIn("Search agents by name", body)
        self.assertIn(expected_featured.name, body)
        self.assertIn(hall_agent.name, body)
        self.assertIn(self.seeded_agent.name, body)
        self.assertNotIn("Keycard Station", body)
        self.assertNotIn("Tools Station", body)

    def test_agent_environment_settings_bootstraps_shared_pool_and_accepts_uploads(self) -> None:
        response = self.client.get("/agents/environment-settings")
        self.assertEqual(200, response.status_code)
        self.assertIn("Shared Background Pool", response.text)
        self.assertIn("Agent Skynet", response.text)

        shared_upload = self.client.post(
            "/agents/environment-settings/shared-backgrounds",
            files={"background_file": ("shared-skynet-test.png", self._tiny_png_bytes(), "image/png")},
            follow_redirects=True,
        )
        self.assertEqual(200, shared_upload.status_code)
        self.assertIn("Shared Skynet background uploaded", shared_upload.text)

        shared_assets = self.client.app.state.agent_environment_appearance_service.list_shared_backgrounds("skynet")
        self.assertTrue(any(asset.display_name == "shared-skynet-test" for asset in shared_assets))

    def test_agent_environment_bay_exposes_appearance_controls_and_custom_backgrounds(self) -> None:
        agent = self._create_agent(name="Appearance Agent")

        response = self.client.get(f"/agent-environment/agents/{agent.id}")
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Appearance", body)
        self.assertIn("Default / Random", body)
        self.assertIn("Theme Assets", body)
        self.assertIn("Upload Custom", body)

        upload = self.client.post(
            f"/agent-environment/agents/{agent.id}/appearance/custom/upload",
            files={"background_file": ("agent-custom.png", self._tiny_png_bytes(), "image/png")},
            follow_redirects=True,
        )
        self.assertEqual(200, upload.status_code)
        self.assertIn("Custom background uploaded and selected for this agent", upload.text)

        preference = self.client.app.state.agent_environment_appearance_service.get_agent_skin_preference(
            agent.id,
            "skynet",
        )
        self.assertIsNotNone(preference)
        self.assertEqual("custom", preference.background_mode)

        hall = self.client.get(f"/agent-environment?agent={agent.id}")
        self.assertEqual(200, hall.status_code)
        self.assertIn("Custom background", hall.text)
        self.assertIn("/agent-environment-assets/skins/skynet/agents/", hall.text)

    def test_tools_projection_reuses_platform_inventory_truth_without_duplicates(self) -> None:
        response = self.client.get(f"/api/agents/{self.seeded_agent.id}/tools")
        self.assertEqual(200, response.status_code)
        payload = response.json()

        self.assertEqual(self.seeded_agent.id, payload["agent_id"])
        self.assertGreater(payload["installed_count"], 0)
        self.assertIn("python.scan_repo", payload["assigned_capability_ids"])
        self.assertTrue(
            any(entry["capability_id"] == "python.scan_repo" for entry in payload["assigned_tools"])
        )
        self.assertFalse(
            any(entry["capability_id"] == "python.scan_repo" for entry in payload["available_tools"])
        )

    def test_assign_and_revoke_tools_updates_agent_truth_and_environment_projection(self) -> None:
        agent = self._create_agent(name="Assignable Agent")

        before = self.client.get(f"/api/agents/{agent.id}/tools")
        self.assertEqual(200, before.status_code)
        self.assertFalse(before.json()["assigned_capability_ids"])
        self.assertTrue(
            any(entry["capability_id"] == "python.scan_repo" for entry in before.json()["available_tools"])
        )

        grant = self.client.post(f"/api/agents/{agent.id}/tools/python.scan_repo")
        self.assertEqual(201, grant.status_code)
        self.assertEqual("python.scan_repo", grant.json()["assignment"]["capability_id"])
        self.assertEqual(
            [("python.scan_repo", "granted")],
            self._assignment_rows_for(agent.id),
        )

        spec = self.client.app.state.agent_service.get_spec(agent.id)
        record = self.client.app.state.agent_service.get_or_raise(agent.id)
        self.assertIn("python.scan_repo", spec.tool_access.allowed_capability_ids)
        self.assertIn("python.scan_repo", record.tool_bindings)

        tools_station = self.client.get(f"/agent-environment/agents/{agent.id}/tools")
        self.assertEqual(200, tools_station.status_code)
        self.assertIn("Tools Station", tools_station.text)
        self.assertIn("Hammer Rack", tools_station.text)
        self.assertIn("python.scan_repo", tools_station.text)

        after_grant = self.client.get(f"/api/agents/{agent.id}/tools")
        self.assertEqual(200, after_grant.status_code)
        self.assertIn("python.scan_repo", after_grant.json()["assigned_capability_ids"])
        self.assertFalse(
            any(entry["capability_id"] == "python.scan_repo" for entry in after_grant.json()["available_tools"])
        )

        revoke = self.client.delete(f"/api/agents/{agent.id}/tools/python.scan_repo")
        self.assertEqual(204, revoke.status_code)
        self.assertEqual(
            [("python.scan_repo", "revoked")],
            self._assignment_rows_for(agent.id),
        )

        after_revoke = self.client.get(f"/api/agents/{agent.id}/tools")
        self.assertEqual(200, after_revoke.status_code)
        self.assertNotIn("python.scan_repo", after_revoke.json()["assigned_capability_ids"])
        self.assertTrue(
            any(entry["capability_id"] == "python.scan_repo" for entry in after_revoke.json()["available_tools"])
        )

    def test_granting_unknown_installed_capability_returns_clean_not_found(self) -> None:
        agent = self._create_agent(name="Missing Tool Agent")
        response = self.client.post(f"/api/agents/{agent.id}/tools/not.a.real.capability")
        self.assertEqual(404, response.status_code)
        self.assertIn("Installed capability not found", response.json()["detail"])

    def test_keycard_assignment_global_toggle_and_tool_file_permissions_are_real(self) -> None:
        agent = self._create_agent(name="Keycard Agent")
        repo_dir, main_path, helper_path = self._create_repo_tree("keycard_agent")

        assign = self.client.post(
            f"/api/agents/{agent.id}/keycard/files",
            json={
                "root_path": str(repo_dir),
                "absolute_paths": [str(main_path), str(helper_path)],
            },
        )
        self.assertEqual(201, assign.status_code)
        self.assertEqual(2, assign.json()["assigned_count"])
        self.assertEqual(
            [
                (str(helper_path), "granted", 0),
                (str(main_path), "granted", 0),
            ],
            self._keycard_rows_for(agent.id),
        )

        global_on = self.client.patch(
            f"/api/agents/{agent.id}/keycard/files/global",
            json={"absolute_path": str(main_path), "enabled": True},
        )
        self.assertEqual(200, global_on.status_code)
        self.assertTrue(global_on.json()["global_tool_eligible"])

        self.client.post(f"/api/agents/{agent.id}/tools/python.extract_file")
        self.assertEqual(
            [(str(main_path), "granted")],
            self._tool_file_rows_for(agent.id, "python.extract_file"),
        )

        tool_off = self.client.patch(
            f"/api/agents/{agent.id}/tool-file-permissions",
            json={
                "capability_id": "python.extract_file",
                "absolute_path": str(main_path),
                "allowed": False,
            },
        )
        self.assertEqual(200, tool_off.status_code)
        self.assertFalse(tool_off.json()["allowed"])
        self.assertEqual(
            [(str(main_path), "revoked")],
            self._tool_file_rows_for(agent.id, "python.extract_file"),
        )

        keycard = self.client.get(f"/api/agents/{agent.id}/keycard")
        self.assertEqual(200, keycard.status_code)
        payload = keycard.json()
        self.assertEqual(2, payload["visible_count"])
        self.assertEqual(1, payload["global_enabled_count"])
        self.assertTrue(any(item["absolute_path"] == str(main_path) for item in payload["visible_files"]))

    def test_keycard_station_renders_explorer_and_file_permissions(self) -> None:
        agent = self._create_agent(name="Explorer Agent")
        repo_dir, main_path, helper_path = self._create_repo_tree("explorer_agent")
        self.client.post(
            f"/api/agents/{agent.id}/keycard/files",
            json={
                "root_path": str(repo_dir),
                "absolute_paths": [str(main_path)],
            },
        )
        self.client.patch(
            f"/api/agents/{agent.id}/keycard/files/global",
            json={"absolute_path": str(main_path), "enabled": True},
        )
        self.client.post(f"/api/agents/{agent.id}/tools/python.extract_file")

        response = self.client.get(
            f"/agent-environment/agents/{agent.id}/keycard",
            params={"root": str(repo_dir)},
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Keycard", body)
        self.assertIn("File Explorer", body)
        self.assertIn("Global", body)
        self.assertIn("helper.py", body)
        self.assertIn("main.py", body)
        self.assertIn("python.extract_file", body)

        remove = self.client.request(
            "DELETE",
            f"/api/agents/{agent.id}/keycard/files",
            json={"absolute_path": str(main_path)},
        )
        self.assertEqual(204, remove.status_code)
        self.assertEqual(
            [(str(main_path), "revoked", 0)],
            self._keycard_rows_for(agent.id),
        )

    def test_tool_access_section_patch_is_blocked_from_mutating_grants(self) -> None:
        agent = self._create_agent(name="Section Patch Agent", tool_bindings=["python.scan_repo"])
        response = self.client.patch(
            f"/api/agents/{agent.id}/sections/tool_access",
            json={
                "allowed_capability_ids": ["not.real"],
                "provider_id": "agent-env-provider",
                "model": "gpt-4o-mini",
            },
        )
        self.assertEqual(409, response.status_code)
        self.assertIn("derived from agent capability grants", response.json()["detail"])

        spec = self.client.app.state.agent_service.get_spec(agent.id)
        self.assertEqual(["python.scan_repo"], spec.tool_access.allowed_capability_ids)
        self.assertEqual(
            [("python.scan_repo", "granted")],
            self._assignment_rows_for(agent.id),
        )

    def test_legacy_tool_projection_tampering_does_not_change_semantic_grants(self) -> None:
        agent = self._create_agent(name="Tamper Agent", tool_bindings=["python.scan_repo"])
        with get_db() as conn:
            conn.execute(
                "UPDATE agents SET tool_bindings = ? WHERE id = ?",
                (json.dumps(["not.real"]), agent.id),
            )
            conn.execute(
                """
                UPDATE agent_sections
                SET data = ?
                WHERE agent_id = ? AND section = 'tool_access'
                """,
                (
                    json.dumps(
                        {
                            "allowed_capability_ids": ["other.fake"],
                            "provider_id": "agent-env-provider",
                            "model": "gpt-4o-mini",
                        }
                    ),
                    agent.id,
                ),
            )
            conn.commit()

        spec = self.client.app.state.agent_service.get_spec(agent.id)
        self.assertEqual(["python.scan_repo"], spec.tool_access.allowed_capability_ids)

        tools_response = self.client.get(f"/api/agents/{agent.id}/tools")
        self.assertEqual(200, tools_response.status_code)
        payload = tools_response.json()
        self.assertEqual(["python.scan_repo"], payload["assigned_capability_ids"])
        self.assertFalse(
            any(entry["capability_id"] == "other.fake" for entry in payload["assigned_tools"])
        )

        agent_list_response = self.client.get("/agents")
        self.assertEqual(200, agent_list_response.status_code)
        self.assertIn("python.scan_repo", agent_list_response.text)
        self.assertNotIn("other.fake", agent_list_response.text)
        self.assertNotIn("not.real", agent_list_response.text)

    def test_agent_forms_no_longer_expose_raw_tool_bindings_inputs(self) -> None:
        create_response = self.client.get("/agents/new")
        self.assertEqual(200, create_response.status_code)
        self.assertIn("Tool assignment now lives in Agent Environment", create_response.text)
        self.assertNotIn('name="tool_bindings_raw"', create_response.text)

        edit_response = self.client.get(f"/agents/{self.seeded_agent.id}/edit")
        self.assertEqual(200, edit_response.status_code)
        self.assertIn("Tool assignment now lives in Agent Environment", edit_response.text)
        self.assertNotIn('name="tool_bindings_raw"', edit_response.text)


if __name__ == "__main__":
    unittest.main()
