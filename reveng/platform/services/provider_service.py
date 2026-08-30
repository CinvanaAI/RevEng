"""ProviderService — read and seed provider records."""
from __future__ import annotations

import os

from reveng.storage.db_connection import get_db
from reveng.platform.models.provider import ProviderRecord
from reveng.platform.utils import now_utc


class ProviderService:
    def list_all(self) -> list[ProviderRecord]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM providers ORDER BY is_default DESC, label ASC"
            ).fetchall()
        return [ProviderRecord.from_row(r) for r in rows]

    def get(self, provider_id: str) -> ProviderRecord | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM providers WHERE id = ?", (provider_id,)
            ).fetchone()
        return ProviderRecord.from_row(row) if row else None

    def get_default(self) -> ProviderRecord | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM providers ORDER BY is_default DESC, label ASC LIMIT 1"
            ).fetchone()
        return ProviderRecord.from_row(row) if row else None

    def seed_from_env(self, env_values: dict[str, str]) -> None:
        """
        Idempotent upsert of default providers based on environment/env-file values.

        Called once at startup.  Existing rows are updated if settings changed.
        """
        ts = now_utc()

        # --- OpenAI ---
        api_key_value = os.environ.get("OPENAI_API_KEY", env_values.get("OPENAI_API_KEY", ""))
        if api_key_value:
            base_url = os.environ.get(
                "OPENAI_BASE_URL",
                env_values.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            ).rstrip("/")
            with get_db() as conn:
                existing = conn.execute(
                    "SELECT id FROM providers WHERE id = 'openai'"
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE providers SET base_url=?, updated_at=? WHERE id='openai'",
                        (base_url, ts),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO providers
                            (id, kind, label, base_url, api_key_env, is_default, created_at, updated_at)
                        VALUES ('openai', 'openai', 'OpenAI', ?, 'OPENAI_API_KEY', 1, ?, ?)
                        """,
                        (base_url, ts, ts),
                    )
                conn.commit()

        # --- Ollama ---
        ollama_url = os.environ.get("OLLAMA_BASE_URL", env_values.get("OLLAMA_BASE_URL", ""))
        if ollama_url:
            ollama_url = ollama_url.rstrip("/")
            with get_db() as conn:
                existing = conn.execute(
                    "SELECT id FROM providers WHERE id = 'ollama'"
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE providers SET base_url=?, updated_at=? WHERE id='ollama'",
                        (ollama_url, ts),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO providers
                            (id, kind, label, base_url, api_key_env, is_default, created_at, updated_at)
                        VALUES ('ollama', 'ollama', 'Ollama', ?, '', 0, ?, ?)
                        """,
                        (ollama_url, ts, ts),
                    )
                conn.commit()
