"""ProviderRecord — persisted provider configuration."""
from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass
class ProviderRecord:
    id: str
    kind: str          # "openai" | "ollama"
    label: str
    base_url: str
    api_key_env: str   # name of the env var that holds the key, or "" if none required
    is_default: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> ProviderRecord:
        return cls(
            id=row["id"],
            kind=row["kind"],
            label=row["label"],
            base_url=row["base_url"],
            api_key_env=row["api_key_env"],
            is_default=bool(row["is_default"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
