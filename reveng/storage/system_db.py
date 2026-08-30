from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from reveng.storage.db_connection import init_db
from reveng.storage.db_migrations import apply_migrations


def resolve_system_db_path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path).expanduser().resolve()
    env_val = os.environ.get("REVENG_DB", "")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return (Path.cwd() / "reveng_platform.db").resolve()


def ensure_system_db_ready(db_path: str | Path | None = None) -> Path:
    resolved = resolve_system_db_path(db_path)
    init_db(resolved)

    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    apply_migrations(conn)
    conn.close()
    return resolved
