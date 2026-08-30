"""Storage-owned thread-local SQLite connection management."""
from __future__ import annotations

import sqlite3
import atexit
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, local
from typing import Generator

_DB_PATH: Path | None = None
_DB_GENERATION = 0
_tlocal = local()
_connections: list[sqlite3.Connection] = []
_connections_lock = Lock()


def close_db_connections() -> None:
    """Close every connection created by the current database generation."""
    global _DB_GENERATION
    with _connections_lock:
        connections = list(_connections)
        _connections.clear()
    for connection in connections:
        try:
            connection.close()
        except sqlite3.Error:
            pass
    _DB_GENERATION += 1
    _tlocal.conn = None
    _tlocal.db_path = None
    _tlocal.generation = None


def init_db(db_path: Path) -> None:
    """Select the database path after closing connections from the prior generation."""
    global _DB_PATH
    close_db_connections()
    _DB_PATH = db_path


def _make_connection() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("Database not initialized. Call init_db() before making queries.")
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    with _connections_lock:
        _connections.append(conn)
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield a thread-local SQLite connection.

    Each thread gets its own connection, created on first use and reused for
    subsequent calls within the same thread.  Rolls back on exception.
    """
    current_path = _DB_PATH
    local_path = getattr(_tlocal, "db_path", None)
    local_generation = getattr(_tlocal, "generation", None)
    if (
        local_generation != _DB_GENERATION
        or (local_path is not None and current_path is not None and local_path != current_path)
    ):
        try:
            existing = getattr(_tlocal, "conn", None)
            if existing is not None:
                existing.close()
        except sqlite3.Error:
            pass
        _tlocal.conn = None
        _tlocal.db_path = None
        _tlocal.generation = None

    if not hasattr(_tlocal, "conn") or _tlocal.conn is None:
        _tlocal.conn = _make_connection()
        _tlocal.db_path = current_path
        _tlocal.generation = _DB_GENERATION
    conn: sqlite3.Connection = _tlocal.conn
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise


atexit.register(close_db_connections)
