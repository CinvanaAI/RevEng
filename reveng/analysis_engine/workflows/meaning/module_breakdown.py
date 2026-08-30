"""Module-level meaning breakdown workflow.

Runs file breakdown first (if not already done), then derives module summaries.
Module identity is PROVISIONAL in Phase 1 (cluster-group heuristics).
"""
from __future__ import annotations

from typing import Any

from reveng.coordination.execution import AgenticExecutor
from reveng.analysis_engine.workflows.meaning.file_breakdown import run_file_breakdown


def run_module_breakdown(
    executor: AgenticExecutor,
    base: dict[str, Any],
    file_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run module-level meaning breakdown. Runs file breakdown if not provided."""
    fr = file_result if file_result is not None else run_file_breakdown(executor, base)

    ms = executor.invoke("meaning.modules.summarize", {
        "file_purpose_records": fr["file_purpose_records"],
        "file_behavior_records": fr["file_behavior_records"],
        "cluster_map": base["cluster_map"],
    })

    return {**fr, **ms}
