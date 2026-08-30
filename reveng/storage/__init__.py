"""
Storage package exports.

Keep imports lazy here so DB-layer modules can import storage submodules without
triggering package-init cycles through framework log writers.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "StoredFrameworkLogRecord",
    "append_framework_log",
    "build_framework_log_sink",
    "ensure_system_db_ready",
    "list_framework_logs_for_run",
    "list_recent_framework_logs",
    "resolve_system_db_path",
    "apply_migrations",
    "get_db",
    "init_db",
]


def __getattr__(name: str) -> Any:
    if name in {
        "StoredFrameworkLogRecord",
        "append_framework_log",
        "build_framework_log_sink",
        "list_framework_logs_for_run",
        "list_recent_framework_logs",
    }:
        from .framework_logs import (
            StoredFrameworkLogRecord,
            append_framework_log,
            build_framework_log_sink,
            list_framework_logs_for_run,
            list_recent_framework_logs,
        )

        exports = {
            "StoredFrameworkLogRecord": StoredFrameworkLogRecord,
            "append_framework_log": append_framework_log,
            "build_framework_log_sink": build_framework_log_sink,
            "list_framework_logs_for_run": list_framework_logs_for_run,
            "list_recent_framework_logs": list_recent_framework_logs,
        }
        return exports[name]

    if name in {"ensure_system_db_ready", "resolve_system_db_path"}:
        from .system_db import ensure_system_db_ready, resolve_system_db_path

        exports = {
            "ensure_system_db_ready": ensure_system_db_ready,
            "resolve_system_db_path": resolve_system_db_path,
        }
        return exports[name]

    if name in {"get_db", "init_db"}:
        from .db_connection import get_db, init_db
        return {"get_db": get_db, "init_db": init_db}[name]

    if name == "apply_migrations":
        from .db_migrations import apply_migrations
        return apply_migrations

    raise AttributeError(name)
