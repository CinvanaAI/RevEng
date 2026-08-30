"""
Result contract for the Coordination Layer.

Defines the standard agent result envelope used by all adapters and the
orchestrator, plus the run identity factory.

All agents conform to this interface:
    Input:  run(inputs: dict, output_dir: str, run_id: str) -> dict
    Output: {
        "agent_id": str,
        "run_id": str,
        "status": "ok" | "error",
        "outputs": dict,
        "error": str | None,
        "provenance": {
            "stage": str,
            "upstream_artifacts": [str],
            "output_artifacts": [str],
        }
    }
"""
from __future__ import annotations

import uuid


def new_run_id() -> str:
    """Generate a unique run identifier."""
    return str(uuid.uuid4())


def make_ok(
    agent_id: str,
    run_id: str,
    outputs: dict,
    upstream: list[str],
    written: list[str],
) -> dict:
    """Build a successful agent result."""
    return {
        "agent_id": agent_id,
        "run_id": run_id,
        "status": "ok",
        "outputs": outputs,
        "error": None,
        "provenance": {
            "stage": agent_id,
            "upstream_artifacts": upstream,
            "output_artifacts": written,
        },
    }


def make_error(
    agent_id: str,
    run_id: str,
    error: str,
    upstream: list[str],
) -> dict:
    """Build a failed agent result."""
    return {
        "agent_id": agent_id,
        "run_id": run_id,
        "status": "error",
        "outputs": {},
        "error": error,
        "provenance": {
            "stage": agent_id,
            "upstream_artifacts": upstream,
            "output_artifacts": [],
        },
    }
