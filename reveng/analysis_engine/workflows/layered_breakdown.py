"""Layered breakdown workflow — full meaning layer over base analysis.

Runs the deterministic base analysis pipeline, then runs the system-level
meaning breakdown (Phase 1: Python-specific heuristics), then composes all
output products via OutputComposer.

Activated via --layered flag.
"""
from __future__ import annotations

from typing import Any

from reveng.coordination.execution import AgenticExecutor
from reveng.analysis_engine.workflows.meaning.system_breakdown import run_system_breakdown
from reveng.framework import WorkflowDefinition, WorkflowRegistry, WorkflowRuntime
from reveng.analysis_engine.meaning.validation import log_violations, validate_crossrefs, validate_meaning_records
from reveng.analysis_engine.output.composition import OutputComposer
from reveng.analysis_engine.workflows.repo_analysis import run_base_analysis

WORKFLOW_ID = "reveng.workflow.layered_breakdown"


def _finalize_layered_outputs(
    base: dict[str, Any],
    meaning: dict[str, Any],
    composed: Any,
) -> dict[str, Any]:
    return {
        # Base analysis outputs
        "inventory_path": base.get("inventory_path"),
        "relation_map_path": base.get("relation_map_path"),
        "file_breakdowns_path": base.get("file_breakdowns_path"),
        "enriched_path": base.get("enriched_path"),
        "cluster_map_path": base.get("cluster_map_path"),
        "flow_map_path": base.get("flow_map_path"),
        "repo_dossier_path": base.get("repo_dossier_path"),
        "validation_report_path": base.get("validation_report_path"),
        "unknowns_path": base.get("unknowns_path"),
        "file_count": base.get("file_count"),
        "error_count": base.get("error_count"),
        "warning_count": base.get("warning_count"),
        # Meaning layer outputs — JSON artifacts
        "ability_records_path": meaning.get("ability_records_path"),
        "action_records_path": meaning.get("action_records_path"),
        "function_meaning_records_path": meaning.get("function_meaning_records_path"),
        "file_purpose_records_path": meaning.get("file_purpose_records_path"),
        "file_behavior_records_path": meaning.get("file_behavior_records_path"),
        "workflow_records_path": meaning.get("workflow_records_path"),
        "module_summary_records_path": meaning.get("module_summary_records_path"),
        "subsystem_summary_records_path": meaning.get("subsystem_summary_records_path"),
        "system_summary_path": meaning.get("system_summary_path"),
        # Counts
        "ability_count": meaning.get("ability_count", 0),
        "action_count": meaning.get("action_count", 0),
        "function_meaning_count": meaning.get("function_meaning_count", 0),
        "file_purpose_count": meaning.get("file_purpose_count", 0),
        "file_behavior_count": meaning.get("file_behavior_count", 0),
        "workflow_count": meaning.get("workflow_count", 0),
        "module_summary_count": meaning.get("module_summary_count", 0),
        "subsystem_summary_count": meaning.get("subsystem_summary_count", 0),
        # Composition outputs — markdown + crossref
        **(composed.output_paths if hasattr(composed, "output_paths") else composed),
    }


def _run_layered_breakdown(runtime: WorkflowRuntime, inputs: dict[str, Any]) -> dict[str, Any]:
    base = run_base_analysis(runtime, inputs)
    executor = AgenticExecutor(runtime)
    meaning = run_system_breakdown(executor, base)

    # Validation runs at the capability invocation boundary — before write, not during write.
    # This is a Capability Platform concern; OutputComposer (Storage Substrate) only writes.
    system_map_data = {k: runtime.read_input(meaning.get(k, [])) for k in (
        "ability_records", "action_records", "function_meaning_records",
        "file_purpose_records", "file_behavior_records", "workflow_records",
        "module_summary_records", "subsystem_summary_records",
    )}
    system_map_data["system_summary_record"] = runtime.read_input(
        meaning.get("system_summary_record", {})
    )
    meaning_violations = validate_meaning_records(system_map_data)
    crossref_violations = validate_crossrefs(system_map_data)
    log_violations(meaning_violations, crossref_violations)
    validation_data = {
        "meaning_violations": meaning_violations,
        "crossref_violations": crossref_violations,
        "total_violations": len(meaning_violations) + len(crossref_violations),
    }

    composer = OutputComposer(runtime.output_dir)
    composed = composer.compose(base, meaning, runtime=runtime, validation_data=validation_data)
    return _finalize_layered_outputs(base, meaning, composed)


def register(registry: WorkflowRegistry) -> None:
    registry.register(WorkflowDefinition(
        workflow_id=WORKFLOW_ID,
        description=(
            "Full layered meaning breakdown (Phase 1: Python-specific heuristics). "
            "Produces: abilities, actions, function meanings, file purposes, file behaviors, "
            "workflows, module summaries [PROVISIONAL], subsystem summaries [PROVISIONAL], "
            "system summary."
        ),
        handler=_run_layered_breakdown,
    ))
