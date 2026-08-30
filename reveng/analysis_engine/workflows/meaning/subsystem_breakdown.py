"""Subsystem-level meaning breakdown workflow.

Runs module breakdown first (if not already done), then derives subsystem summaries.
Subsystem identity is PROVISIONAL in Phase 1 (path-prefix heuristics).
"""
from __future__ import annotations

from typing import Any

from reveng.coordination.execution import AgenticExecutor
from reveng.analysis_engine.workflows.meaning.module_breakdown import run_module_breakdown


def run_subsystem_breakdown(
    executor: AgenticExecutor,
    base: dict[str, Any],
    module_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run subsystem-level meaning breakdown. Runs module breakdown if not provided."""
    mr = module_result if module_result is not None else run_module_breakdown(executor, base)

    ss = executor.invoke("meaning.subsystems.summarize", {
        "module_summary_records": mr["module_summary_records"],
        "cluster_map": base["cluster_map"],
    })

    return {**mr, **ss}
