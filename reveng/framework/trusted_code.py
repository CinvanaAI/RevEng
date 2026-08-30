"""Opt-in gate for executing user-authored Python inside the RevEng process."""
from __future__ import annotations

import os


AUTHORED_CODE_ENV = "REVENG_ENABLE_AUTHORED_CODE"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def authored_code_execution_enabled() -> bool:
    return os.environ.get(AUTHORED_CODE_ENV, "").strip().casefold() in _TRUE_VALUES


def require_authored_code_execution_enabled(source_kind: str) -> None:
    if authored_code_execution_enabled():
        return
    raise PermissionError(
        f"Execution of {source_kind} is disabled by default. "
        f"Set {AUTHORED_CODE_ENV}=1 in the process environment only after "
        "reviewing the code and accepting that it runs with this process's full OS access."
    )


__all__ = [
    "AUTHORED_CODE_ENV",
    "authored_code_execution_enabled",
    "require_authored_code_execution_enabled",
]
