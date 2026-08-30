from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from reveng.capabilities.environment import (
    CAPABILITY_ENVIRONMENT_CANONICAL_ACTION_IDS,
    CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID,
    CAPABILITY_ENVIRONMENT_SKIN_PACKAGES,
)
from reveng.storage.db_connection import get_db
from reveng.platform.utils import now_utc
from reveng.platform.web.app import create_app


class CapabilityEnvironmentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = Path(__file__).resolve().parent / "_capability_environment_ui"
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
                    "ui-test-provider",
                    "openai",
                    "UI Test Provider",
                    "https://example.invalid/v1",
                    "OPENAI_API_KEY",
                    1,
                    ts,
                    ts,
                ),
            )
            conn.commit()

        cls.agent = cls.client.app.state.agent_service.create(
            name="Workshop Agent",
            provider_id="ui-test-provider",
            model="gpt-4o-mini",
            tool_bindings=["python.scan_repo"],
        )
        cls.draft = cls.client.app.state.capability_draft_service.create_draft(
            name="Workshop Draft",
            description="Draft used for shell route coverage.",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_ctx.__exit__(None, None, None)
        if cls._old_db_env is None:
            os.environ.pop("REVENG_DB", None)
        else:
            os.environ["REVENG_DB"] = cls._old_db_env
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def setUp(self) -> None:
        self.client.app.state.capability_environment_service.update_settings(
            enable_skins=False,
            selected_skin_id="random",
        )

    def test_agent_detail_exposes_toolbox_launch(self) -> None:
        response = self.client.get(f"/agents/{self.agent.id}")
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Agent Environment", body)
        self.assertIn("Open Tools Station", body)
        self.assertIn(
            f"/agent-environment/agents/{self.agent.id}",
            body,
        )

    def test_legacy_launch_route_redirects_to_direct_environment_entry(self) -> None:
        response = self.client.get(
            f"/capability-environment/launch?return=/agents/{self.agent.id}",
            follow_redirects=False,
        )
        self.assertEqual(303, response.status_code)
        self.assertEqual("/capability-environment", response.headers["location"])

    def test_capability_button_opens_platform_workspace_directly(self) -> None:
        response = self.client.get(
            f"/capabilities?return=/agents/{self.agent.id}"
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Capability Platform Workspace", body)
        self.assertIn("direct main-window manifestation of Capability Platform", body)
        self.assertIn("Coordinated Changeset Drafts", body)
        self.assertIn("Publication / Install Activity", body)
        self.assertIn("Installed Capabilities", body)
        self.assertIn("Create Draft", body)
        self.assertIn("Control Center", body)
        self.assertIn("Capability Environment", body)
        self.assertNotIn("Workspace Bridges", body)
        self.assertNotIn("/capability-environment/drafts/", body)

    def test_environment_root_renders_neutral_workshop_when_skins_are_disabled(self) -> None:
        response = self.client.get(
            f"/capability-environment?return=/agents/{self.agent.id}",
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Workshop Floor", body)
        self.assertIn("neutral workshop floor", body)
        self.assertIn("Create Draft", body)
        self.assertIn("Inspect Installed", body)
        self.assertIn("Capabilities", body)

    def test_skin_surface_wires_workbench_and_return_hotspots_to_real_navigation(self) -> None:
        selected_skin = CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID["capability_workshop"]
        self.client.app.state.capability_environment_service.update_settings(
            enable_skins=True,
            selected_skin_id="random",
        )
        with patch(
            "reveng.execution_environment.capability_environment.skins.choose_random_capability_environment_skin_package",
            return_value=selected_skin,
        ):
            response = self.client.get(
                f"/capability-environment?return=/agents/{self.agent.id}"
            )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn('data-action-id="workbench"', body)
        self.assertIn(
            f'data-target-url="/capability-environment/skins/{selected_skin.skin_id}?station=workbench"',
            body,
        )
        self.assertIn('data-action-id="return"', body)
        self.assertIn('data-target-url="/capabilities"', body)
        self.assertIn("Capability Platform", body)
        self.assertIn("Settings", body)

    def test_legacy_draft_route_resolves_to_environment_draft_surface(self) -> None:
        response = self.client.get(
            f"/capability-environment/drafts/{self.draft.id}?return=/agents/{self.agent.id}"
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Workshop Floor", body)
        self.assertIn(self.draft.name, body)
        self.assertIn("Draft Boundary", body)
        self.assertIn("Draft Overview", body)
        self.assertIn("Cancel Changes", body)
        self.assertIn("Leave Draft", body)
        self.assertIn("Save New Version", body)
        self.assertIn("Capabilities", body)
        self.assertNotIn("Workshop Path", body)
        self.assertNotIn("Active Station", body)

    def test_legacy_station_route_redirects_into_environment_place(self) -> None:
        response = self.client.get(
            f"/capability-environment/stations/workbench?return=/agents/{self.agent.id}",
            follow_redirects=False,
        )
        self.assertEqual(303, response.status_code)
        self.assertEqual(
            "/capability-environment?station=workbench",
            response.headers["location"],
        )

    def test_workbench_station_renders_real_draft_inventory_inside_place(self) -> None:
        response = self.client.get(
            f"/capability-environment?return=/agents/{self.agent.id}&station=workbench"
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Workbench", body)
        self.assertIn("Persistent Draft Inventory", body)
        self.assertIn(self.draft.name, body)
        self.assertIn("Create Draft", body)
        self.assertIn("Capabilities", body)

    def test_create_draft_station_renders_environment_owned_intake(self) -> None:
        response = self.client.get(
            f"/capability-environment?return=/agents/{self.agent.id}&station=create_draft"
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Draft Forge", body)
        self.assertIn("Draft Creation", body)
        self.assertIn("Opening this forge does not persist anything", body)
        self.assertIn("/api/capability-environment/stations/create-draft", body)
        self.assertNotIn('fetch("/api/capability-environment/drafts"', body)

    def test_create_draft_station_api_creates_real_draft(self) -> None:
        response = self.client.post(
            "/api/capability-environment/stations/create-draft",
            json={
                "name": "Station-Owned Draft",
                "description": "Created through create_draft station orchestration.",
            },
        )
        self.assertEqual(201, response.status_code)
        draft = response.json()
        self.assertEqual("Station-Owned Draft", draft["name"])

        persisted = self.client.get(f"/api/capability-environment/drafts/{draft['id']}")
        self.assertEqual(200, persisted.status_code)
        self.assertEqual(
            "Station-Owned Draft",
            persisted.json()["name"],
        )

    def test_inventory_wall_station_fetches_real_installed_capability_detail(self) -> None:
        response = self.client.get(
            f"/capability-environment?return=/agents/{self.agent.id}&station=inventory_wall"
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Inventory Wall", body)
        self.assertIn("/api/capability-environment/inventory/", body)
        self.assertIn("Stored capability record history", body)
        self.assertIn("Settings", body)

    def test_inventory_detail_api_returns_platform_record_and_events(self) -> None:
        response = self.client.get("/api/capability-environment/inventory/python.scan_repo")
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("python.scan_repo", payload["capability_id"])
        self.assertEqual("installed", payload["lifecycle_state"])
        self.assertIn("source_kind", payload)
        self.assertIn("source_ref", payload)
        self.assertIn("package_object", payload)
        self.assertEqual("python.scan_repo", payload["package_object"]["capability_id"])
        self.assertIn("record_events", payload)
        self.assertGreaterEqual(len(payload["record_events"]), 1)
        self.assertIn(payload["record_events"][0]["event_type"], {"installed", "restored", "updated"})

    def test_platform_capability_routes_expose_platform_owned_detail_and_draft_seed(self) -> None:
        detail_response = self.client.get("/api/capabilities/python.scan_repo")
        self.assertEqual(200, detail_response.status_code)
        detail = detail_response.json()
        self.assertEqual("python.scan_repo", detail["capability_id"])
        self.assertEqual("installed", detail["lifecycle_state"])
        self.assertIsNotNone(detail["package_object"])

        seed_response = self.client.get("/api/capabilities/python.scan_repo/draft-seed")
        self.assertEqual(200, seed_response.status_code)
        seed = seed_response.json()
        self.assertEqual("python.scan_repo", seed["planned_capability_id"])
        self.assertEqual(
            detail["package_object"]["id"],
            seed["draft_data"]["derived_from_package_object_id"],
        )

    def test_platform_workspace_exposes_real_platform_draft_pages(self) -> None:
        create_response = self.client.post(
            f"/capabilities/drafts?return=/agents/{self.agent.id}",
            data={
                "name": "Workspace-Owned Draft",
                "description": "Created from the platform workspace.",
                "version": "1.0.0",
            },
            follow_redirects=False,
        )
        self.assertEqual(303, create_response.status_code)
        draft_location = create_response.headers["location"]
        self.assertIn("/capabilities/drafts/", draft_location)

        detail_response = self.client.get(draft_location)
        self.assertEqual(200, detail_response.status_code)
        body = detail_response.text
        self.assertIn("Draft Overview", body)
        self.assertIn("Draft Items", body)
        self.assertIn("Ledger / History", body)
        self.assertIn("Publish to Live", body)
        self.assertNotIn("/capability-environment/stations/", body)

    def test_platform_live_capability_page_exposes_package_truth_and_copy_flow(self) -> None:
        detail_response = self.client.get(
            f"/capabilities/live/python.scan_repo?return=/agents/{self.agent.id}"
        )
        self.assertEqual(200, detail_response.status_code)
        body = detail_response.text
        self.assertIn("python.scan_repo", body)
        self.assertIn("Unpublished", body)
        self.assertIn("Published Surface", body)
        self.assertIn("Propose Edit", body)

        copy_response = self.client.post(
            f"/capabilities/live/python.scan_repo/drafts?return=/agents/{self.agent.id}",
            follow_redirects=False,
        )
        self.assertEqual(303, copy_response.status_code)
        self.assertIn("/capabilities/drafts/", copy_response.headers["location"])

    def test_platform_package_object_page_opens_stored_snapshot_truth(self) -> None:
        detail = self.client.get("/api/capabilities/python.scan_repo").json()
        package_id = detail["package_object"]["id"]
        response = self.client.get(
            f"/capabilities/packages/{package_id}?return=/agents/{self.agent.id}"
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("python.scan_repo", body)
        self.assertIn("Published Surface", body)
        self.assertIn("History", body)

    def test_settings_page_exposes_environment_manifestation_controls(self) -> None:
        response = self.client.get(
            f"/capabilities/settings?return=/agents/{self.agent.id}"
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Capability Environment Settings", body)
        self.assertIn("Enable Skins?", body)
        self.assertIn("Selected Skin", body)
        self.assertIn("Random", body)
        self.assertIn("Capability Platform", body)
        self.assertIn("main-window workspace", body)

    def test_legacy_environment_settings_route_redirects_to_capabilities_settings(self) -> None:
        response = self.client.get(
            f"/capability-environment/settings?return=/agents/{self.agent.id}",
            follow_redirects=False,
        )
        self.assertEqual(303, response.status_code)
        self.assertEqual("/capabilities/settings", response.headers["location"])

    def test_settings_post_controls_entry_manifestation(self) -> None:
        response = self.client.post(
            f"/capabilities/settings?return=/agents/{self.agent.id}",
            data={
                "enable_skins": "1",
                "selected_skin_id": "weapons_cache",
            },
            follow_redirects=False,
        )
        self.assertEqual(303, response.status_code)
        self.assertEqual("/capabilities/settings", response.headers["location"])

        settings = self.client.app.state.capability_environment_service.get_settings()
        self.assertTrue(settings.enable_skins)
        self.assertEqual("weapons_cache", settings.selected_skin_id)

    def test_capability_workspace_ignores_skin_settings(self) -> None:
        self.client.app.state.capability_environment_service.update_settings(
            enable_skins=True,
            selected_skin_id="weapons_cache",
        )
        response = self.client.get(
            f"/capabilities?return=/agents/{self.agent.id}"
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("Capability Platform Workspace", response.text)
        self.assertNotIn("Weapons Cache", response.text)

    def test_environment_root_stays_skin_only_when_skins_are_enabled(self) -> None:
        self.client.app.state.capability_environment_service.update_settings(
            enable_skins=True,
            selected_skin_id="weapons_cache",
        )
        response = self.client.get(
            f"/capability-environment?return=/agents/{self.agent.id}"
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Weapons Cache", body)
        self.assertIn("Capability Environment", body)
        self.assertIn("Manifestation", body)
        self.assertIn("Capability Platform", body)

    def test_direct_skin_route_renders_specific_skin_manifestation(self) -> None:
        response = self.client.get(
            f"/capability-environment/skins/weapons_cache?return=/agents/{self.agent.id}"
        )
        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Weapons Cache", body)
        self.assertIn("Manifestation", body)
        self.assertIn("Capability Platform", body)
        self.assertIn("Settings", body)
        self.assertIn(
            'data-target-url="/capability-environment/skins/weapons_cache?station=workbench"',
            body,
        )

    def test_direct_skin_route_returns_clean_not_found_for_unknown_skin(self) -> None:
        response = self.client.get(
            f"/capability-environment/skins/not-a-real-skin?return=/agents/{self.agent.id}"
        )
        self.assertEqual(404, response.status_code)
        body = response.text
        self.assertIn("Skin Not Found", body)
        self.assertIn("not-a-real-skin", body)
        self.assertIn("Capability Platform", body)
        self.assertIn("Settings", body)

    def test_professional_route_is_now_only_a_compatibility_redirect(self) -> None:
        response = self.client.get(
            f"/capabilities/professional?return=/agents/{self.agent.id}",
            follow_redirects=False,
        )
        self.assertEqual(303, response.status_code)
        self.assertEqual("/capabilities", response.headers["location"])

    def test_legacy_environment_professional_route_redirects_to_capabilities_professional(self) -> None:
        response = self.client.get(
            f"/capability-environment/professional?return=/agents/{self.agent.id}",
            follow_redirects=False,
        )
        self.assertEqual(303, response.status_code)
        self.assertEqual("/capabilities", response.headers["location"])

    def test_workbench_flow_is_live_end_to_end(self) -> None:
        create_response = self.client.post(
            "/api/capability-environment/drafts",
            json={
                "name": "Workbench Integration Draft",
                "description": "Created through the live API.",
            },
        )
        self.assertEqual(201, create_response.status_code)
        draft = create_response.json()
        draft_id = draft["id"]

        workbench_response = self.client.get(
            f"/capability-environment?return=/agents/{self.agent.id}&station=workbench"
        )
        self.assertEqual(200, workbench_response.status_code)
        self.assertIn("Workbench Integration Draft", workbench_response.text)

        detail_response = self.client.get(
            f"/capability-environment/drafts/{draft_id}?return=/agents/{self.agent.id}"
        )
        self.assertEqual(200, detail_response.status_code)
        self.assertIn("Save Details", detail_response.text)
        self.assertIn("Save New Version", detail_response.text)
        self.assertIn("Add Draft Item", detail_response.text)

        rename_response = self.client.patch(
            f"/api/capability-environment/drafts/{draft_id}",
            json={
                "name": "Workbench Integration Draft Renamed",
                "description": "Updated in the live workbench flow.",
            },
        )
        self.assertEqual(200, rename_response.status_code)
        self.assertEqual("Workbench Integration Draft Renamed", rename_response.json()["name"])

        add_item_response = self.client.post(
            f"/api/capability-environment/drafts/{draft_id}/items",
            json={
                "planned_capability_id": "test.workbench_live",
                "draft_data": {
                    "capability_id": "test.workbench_live",
                    "display_name": "Workbench Live Capability",
                    "description": "Created through the workbench integration test.",
                    "capability_type": "base",
                    "contract": {"inputs": [], "output": [], "constraints": []},
                    "version": "1.0.0",
                },
            },
        )
        self.assertEqual(201, add_item_response.status_code)
        item = add_item_response.json()

        update_item_response = self.client.patch(
            f"/api/capability-environment/drafts/{draft_id}/items/{item['id']}",
            json={
                "draft_data": {
                    "capability_id": "test.workbench_live",
                    "display_name": "Workbench Live Capability Updated",
                    "description": "Updated through the workbench integration test.",
                    "capability_type": "base",
                    "contract": {"inputs": [], "output": [], "constraints": []},
                    "version": "1.0.0",
                },
            },
        )
        self.assertEqual(200, update_item_response.status_code)
        self.assertEqual("draft", update_item_response.json()["item_state"])

        save_version_response = self.client.post(
            f"/api/capability-environment/drafts/{draft_id}/versions",
            json={"version": "2.0.0"},
        )
        self.assertEqual(201, save_version_response.status_code)
        self.assertEqual("2.0.0", save_version_response.json()["version"])

        revision_history_response = self.client.get(
            f"/api/capability-environment/drafts/{draft_id}/revisions"
        )
        self.assertEqual(200, revision_history_response.status_code)
        revisions = revision_history_response.json()["revisions"]
        self.assertEqual(1, len(revisions))
        self.assertEqual("2.0.0", revisions[0]["version"])

        live_draft_response = self.client.get(
            f"/api/capability-environment/drafts/{draft_id}"
        )
        self.assertEqual(200, live_draft_response.status_code)
        self.assertEqual("Workbench Integration Draft Renamed", live_draft_response.json()["name"])
        self.assertEqual(1, len(live_draft_response.json()["items"]))

        delete_item_response = self.client.delete(
            f"/api/capability-environment/drafts/{draft_id}/items/{item['id']}"
        )
        self.assertEqual(204, delete_item_response.status_code)

        delete_draft_response = self.client.delete(
            f"/api/capability-environment/drafts/{draft_id}"
        )
        self.assertEqual(204, delete_draft_response.status_code)

        missing_draft_response = self.client.get(
            f"/api/capability-environment/drafts/{draft_id}"
        )
        self.assertEqual(404, missing_draft_response.status_code)

    def test_ledger_surface_shows_platform_publication_candidates(self) -> None:
        create_response = self.client.post(
            "/api/capability-environment/drafts",
            json={
                "name": "Ledger Candidate Draft",
                "description": "Used to verify ledger candidate rendering.",
            },
        )
        self.assertEqual(201, create_response.status_code)
        draft_id = create_response.json()["id"]

        add_item_response = self.client.post(
            f"/api/capability-environment/drafts/{draft_id}/items",
            json={
                "planned_capability_id": "test.ledger_candidate",
                "draft_data": {
                    "capability_id": "test.ledger_candidate",
                    "display_name": "Ledger Candidate",
                    "description": "Candidate shown in ledger.",
                    "capability_type": "base",
                    "contract": {"inputs": [], "output": [], "constraints": []},
                    "version": "1.0.0",
                    "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
                },
            },
        )
        self.assertEqual(201, add_item_response.status_code)

        validate_response = self.client.post(
            f"/api/capability-environment/drafts/{draft_id}/validate"
        )
        self.assertEqual(200, validate_response.status_code)

        publish_response = self.client.post(
            f"/api/capability-environment/drafts/{draft_id}/publish"
        )
        self.assertEqual(200, publish_response.status_code)

        ledger_response = self.client.get(
            f"/capability-environment/drafts/{draft_id}?return=/agents/{self.agent.id}&station=ledger"
        )
        self.assertEqual(200, ledger_response.status_code)
        body = ledger_response.text
        self.assertIn("Platform Publication Candidates", body)
        self.assertIn("Stored candidate records for", body)
        self.assertIn("test.ledger_candidate", body)
        self.assertIn("ready", body)

    def test_ledger_surface_exposes_real_rollback_actions(self) -> None:
        create_response = self.client.post(
            "/api/capability-environment/drafts",
            json={
                "name": "Ledger Rollback Draft",
                "description": "Used to verify ledger rollback actions.",
            },
        )
        self.assertEqual(201, create_response.status_code)
        draft_id = create_response.json()["id"]

        add_item_response = self.client.post(
            f"/api/capability-environment/drafts/{draft_id}/items",
            json={
                "planned_capability_id": "test.ledger_rollback",
                "draft_data": {
                    "capability_id": "test.ledger_rollback",
                    "display_name": "Ledger Rollback V1",
                    "description": "Rollback-ready version.",
                    "capability_type": "base",
                    "version": "1.0.0",
                    "contract": {"inputs": [], "output": [], "constraints": []},
                    "implementation_ref": "reveng.analysis_engine.packs.python_static:_scan_repo",
                },
            },
        )
        self.assertEqual(201, add_item_response.status_code)

        version_response = self.client.post(
            f"/api/capability-environment/drafts/{draft_id}/versions",
            json={"version": "1.1.0"},
        )
        self.assertEqual(201, version_response.status_code)

        validate_response = self.client.post(
            f"/api/capability-environment/drafts/{draft_id}/validate"
        )
        self.assertEqual(200, validate_response.status_code)

        publish_response = self.client.post(
            f"/api/capability-environment/drafts/{draft_id}/publish"
        )
        self.assertEqual(200, publish_response.status_code)

        ledger_response = self.client.get(
            f"/capability-environment/drafts/{draft_id}?return=/agents/{self.agent.id}&station=ledger"
        )
        self.assertEqual(200, ledger_response.status_code)
        body = ledger_response.text
        self.assertIn("Rollback Rule", body)
        self.assertIn("Restore Live", body)
        self.assertIn("Republish Live", body)
        self.assertIn(f"/api/capability-environment/drafts/{draft_id}/rollback/revisions/", body)
        self.assertIn(f"/api/capability-environment/drafts/{draft_id}/rollback/publications/", body)

    def test_environment_root_can_resolve_different_random_skin_packages_on_reentry(self) -> None:
        self.client.app.state.capability_environment_service.update_settings(
            enable_skins=True,
            selected_skin_id="random",
        )
        first_skin = CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID["capability_workshop"]
        second_skin = CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID["arcane_archives"]
        with patch(
            "reveng.execution_environment.capability_environment.skins.choose_random_capability_environment_skin_package",
            side_effect=[first_skin, second_skin],
        ):
            first_response = self.client.get(
                f"/capability-environment?return=/agents/{self.agent.id}"
            )
            second_response = self.client.get(
                f"/capability-environment?return=/agents/{self.agent.id}"
            )

        self.assertEqual(200, first_response.status_code)
        self.assertEqual(200, second_response.status_code)
        self.assertIn("Capability Workshop", first_response.text)
        self.assertIn("Arcane Archives", second_response.text)
        self.assertNotEqual(first_response.text, second_response.text)

    def test_skin_registry_keeps_six_canonical_hotspots_per_skin(self) -> None:
        self.assertEqual(6, len(CAPABILITY_ENVIRONMENT_SKIN_PACKAGES))
        expected_actions = set(CAPABILITY_ENVIRONMENT_CANONICAL_ACTION_IDS)
        for skin in CAPABILITY_ENVIRONMENT_SKIN_PACKAGES:
            hotspot_actions = {hotspot.action_id for hotspot in skin.hotspots}
            self.assertEqual(6, len(skin.hotspots))
            self.assertEqual(expected_actions, hotspot_actions)


if __name__ == "__main__":
    unittest.main()
