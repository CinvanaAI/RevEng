from __future__ import annotations

import shutil
import sqlite3
import unittest
from pathlib import Path

from reveng.storage.db_connection import init_db, get_db
from reveng.storage.db_migrations import apply_migrations
from reveng.platform.services.agent_service import AgentService
from reveng.platform.services.analysis_bridge import _resolve_provider_for_run
from reveng.platform.services.provider_service import ProviderService


class ProviderResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = Path(__file__).resolve().parent / "_provider_resolution"
        shutil.rmtree(cls.workspace, ignore_errors=True)
        cls.workspace.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.workspace / "platform.db"
        init_db(cls.db_path)
        conn = sqlite3.connect(str(cls.db_path))
        apply_migrations(conn)
        conn.execute(
            """
            INSERT INTO providers
                (id, kind, label, base_url, api_key_env, is_default, created_at, updated_at)
            VALUES
                ('default-ollama', 'ollama', 'Default Ollama', 'http://localhost:11434/v1', '', 1, 'now', 'now'),
                ('agent-ollama', 'ollama', 'Agent Ollama', 'http://localhost:11435/v1', '', 0, 'now', 'now')
            """
        )
        conn.commit()
        conn.close()
        cls.provider_svc = ProviderService()
        cls.agent_svc = AgentService()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def test_platform_run_uses_default_provider_record(self) -> None:
        provider = _resolve_provider_for_run(
            with_ai=True,
            layered=False,
            env_file=".env",
            provider_service=self.provider_svc,
            agent_service=None,
            agent_id=None,
        )
        self.assertEqual("default-ollama", provider.provider_id)
        self.assertEqual("gpt-4o-mini", provider.model)

    def test_agent_run_uses_agent_provider_and_model(self) -> None:
        agent = self.agent_svc.create(
            name="Provider Test Agent",
            provider_id="agent-ollama",
            model="agent-model",
            tool_bindings=["python.scan_repo"],
        )
        self.agent_svc.set_active(agent.id, True)

        provider = _resolve_provider_for_run(
            with_ai=True,
            layered=False,
            env_file=".env",
            provider_service=self.provider_svc,
            agent_service=self.agent_svc,
            agent_id=agent.id,
        )
        self.assertEqual("agent-ollama", provider.provider_id)
        self.assertEqual("agent-model", provider.model)


if __name__ == "__main__":
    unittest.main()
