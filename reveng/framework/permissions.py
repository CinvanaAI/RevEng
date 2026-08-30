"""Explicit capability permission policies used at trusted boundaries."""
from __future__ import annotations

from typing import Any


def trusted_local_capability_check(
    capability_id: str,
    inputs: dict[str, Any],
) -> bool:
    """Allow registered built-ins for an explicitly trusted local analysis run.

    This is not a sandbox. Agent-authored workflows use the agent permission
    service instead and must not substitute this policy.
    """

    del capability_id, inputs
    return True


__all__ = ["trusted_local_capability_check"]
