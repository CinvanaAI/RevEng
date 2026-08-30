"""Parallel-phase wrapper capabilities for the Analysis Agent pipeline.

Registers five capabilities that handle fan-out phases the base pipeline runs
in parallel.  Single-invocation capabilities (python.scan_repo, python.inventory
.assemble, python.relations.build, python.flows.build) are NOT wrapped here —
the agent workflow calls them directly via capability_registry["..."]().

Each wrapper uses AgenticExecutor or direct business-logic calls to run parallel
work inside the capability boundary, then returns assembled results.  All artifact
writes are recorded via ctx.record_artifact() so paths propagate to OutputService
through the bridge's runtime.written_paths mechanism.
"""
from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any

from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)

PACK_ID = "reveng.pack.analysis_pipeline"


# ---------------------------------------------------------------------------
# analysis_extract_files
# ---------------------------------------------------------------------------

def _analysis_extract_files(context: CapabilityContext) -> dict[str, Any]:
    """Parallel extraction of all Python files discovered by python.scan_repo."""
    from reveng.analysis_engine.analysis.extractor import extract_file_record, module_name_from_path

    repo_root = Path(context.require("repo_root"))
    scan_data = context.read_input("scan_result")
    file_paths: list[str] = scan_data.get("file_paths", [])
    workers = int(context.get("extractor_workers") or 6)

    def _extract(file_path_str: str) -> dict[str, Any]:
        fp = Path(file_path_str)
        try:
            return extract_file_record(repo_root, fp)
        except SyntaxError as exc:
            rel = fp.relative_to(repo_root).as_posix()
            return {
                "path": rel,
                "module_name": module_name_from_path(repo_root, fp),
                "parse_error": f"SyntaxError: {exc}",
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_extract, fp): fp for fp in file_paths}
        file_records = [f.result() for f in concurrent.futures.as_completed(futures)]

    file_records.sort(key=lambda r: r.get("path", ""))
    return {"file_records": file_records}


# ---------------------------------------------------------------------------
# analysis_build_breakdowns
# ---------------------------------------------------------------------------

def _analysis_build_breakdowns(context: CapabilityContext) -> dict[str, Any]:
    """Run python.file_breakdowns.enrich and python.clusters.build in parallel."""
    from reveng.coordination.execution import AgenticExecutor

    executor = AgenticExecutor(context.runtime)
    file_breakdowns_ref = context.require("file_breakdowns")
    inventory_ref = context.require("inventory")
    relation_map_ref = context.require("relation_map")

    [enrich_result, cluster_result] = executor.invoke_parallel(
        [
            ("python.file_breakdowns.enrich", {"file_breakdowns": file_breakdowns_ref}),
            ("python.clusters.build", {"inventory": inventory_ref, "relation_map": relation_map_ref}),
        ],
        max_workers=2,
    )

    return {
        "enriched_file_breakdowns": enrich_result["enriched_file_breakdowns"],
        "enriched_path": enrich_result["enriched_path"],
        "cluster_map": cluster_result["cluster_map"],
        "cluster_map_path": cluster_result["cluster_map_path"],
    }


# ---------------------------------------------------------------------------
# analysis_build_reports
# ---------------------------------------------------------------------------

def _analysis_build_reports(context: CapabilityContext) -> dict[str, Any]:
    """Run report.repo_dossier.build, report.validate, report.unknowns.build in parallel."""
    from reveng.coordination.execution import AgenticExecutor

    executor = AgenticExecutor(context.runtime)
    inventory_ref = context.require("inventory")
    relation_map_ref = context.require("relation_map")
    file_breakdowns_ref = context.require("file_breakdowns")
    cluster_map_ref = context.require("cluster_map")
    flow_map_ref = context.require("flow_map")
    enriched_ref = context.require("enriched_file_breakdowns")

    [dossier_result, validation_result, unknowns_result] = executor.invoke_parallel(
        [
            (
                "report.repo_dossier.build",
                {
                    "inventory": inventory_ref,
                    "relation_map": relation_map_ref,
                    "file_breakdowns": file_breakdowns_ref,
                    "cluster_map": cluster_map_ref,
                    "flow_map": flow_map_ref,
                },
            ),
            (
                "report.validate",
                {
                    "inventory": inventory_ref,
                    "relation_map": relation_map_ref,
                    "file_breakdowns": file_breakdowns_ref,
                    "flow_map": flow_map_ref,
                },
            ),
            (
                "report.unknowns.build",
                {
                    "inventory": inventory_ref,
                    "relation_map": relation_map_ref,
                    "cluster_map": cluster_map_ref,
                    "flow_map": flow_map_ref,
                    "enriched_file_breakdowns": enriched_ref,
                },
            ),
        ],
        max_workers=3,
    )

    return {
        "repo_dossier": dossier_result["repo_dossier"],
        "repo_dossier_path": dossier_result["repo_dossier_path"],
        "validation_report": validation_result["validation_report"],
        "validation_report_path": validation_result["validation_report_path"],
        "error_count": validation_result["error_count"],
        "warning_count": validation_result["warning_count"],
        "unknowns": unknowns_result["unknowns"],
        "unknowns_path": unknowns_result["unknowns_path"],
    }


# ---------------------------------------------------------------------------
# analysis_narrate
# ---------------------------------------------------------------------------

def _analysis_narrate(context: CapabilityContext) -> dict[str, Any]:
    """Run the full LLM narration pipeline over base analysis outputs."""
    from reveng.coordination.execution import AgenticExecutor

    executor = AgenticExecutor(context.runtime)

    repo_root: str = context.require("repo_root")
    scanned_at: str = context.require("scanned_at")
    env_file: str = context.get("env_file") or ".env"
    ai_file_workers = int(context.get("ai_file_workers") or 10)
    ai_limit = context.get("ai_limit")

    cluster_map_ref = context.require("cluster_map")
    flow_map_ref = context.require("flow_map")
    enriched_ref = context.require("enriched_file_breakdowns")
    repo_dossier_ref = context.require("repo_dossier")

    cluster_data: dict = context.read(cluster_map_ref)
    flow_data: dict = context.read(flow_map_ref)
    enriched_data: dict = context.read(enriched_ref)

    # Per-file structural context
    ctx_result = executor.invoke("python.context.per_file.build", {
        "cluster_map": cluster_map_ref,
        "flow_map": flow_map_ref,
    })
    per_file_ctx: dict = ctx_result["per_file_context"]

    # Parallel file explanations
    files_to_explain = [
        item for item in enriched_data.get("files", []) if "parse_error" not in item
    ]
    if ai_limit is not None:
        files_to_explain = files_to_explain[:int(ai_limit)]

    explain_calls = [
        (
            "llm.file.explain",
            {
                "file_record": file_record,
                "file_context": per_file_ctx.get(file_record["path"]),
                "repo_root": repo_root,
                "env_file": env_file,
                "index": i,
            },
        )
        for i, file_record in enumerate(files_to_explain, start=1)
    ]
    explain_results = executor.invoke_parallel(explain_calls, max_workers=ai_file_workers)

    ai_file_result = executor.invoke("llm.file.explanations.assemble", {
        "explanation_results": explain_results,
        "repo_root": repo_root,
        "scanned_at": scanned_at,
        "env_file": env_file,
    })

    # Parallel cluster summaries
    clusters = cluster_data.get("clusters", [])
    cross_cluster_edges = cluster_data.get("cross_cluster_edges", [])
    cluster_calls = [
        (
            "llm.cluster.summarize",
            {
                "cluster": cluster,
                "cross_cluster_edges": cross_cluster_edges,
                "flow_map": flow_map_ref,
                "enriched_file_breakdowns": enriched_ref,
                "env_file": env_file,
            },
        )
        for cluster in clusters
    ]
    cluster_results = executor.invoke_parallel(
        cluster_calls, max_workers=max(len(clusters), 1)
    )
    cluster_summaries = [r["cluster_summary"] for r in cluster_results]

    ai_cluster_result = executor.invoke("llm.cluster.summaries.assemble", {
        "cluster_summaries": cluster_summaries,
        "repo_root": repo_root,
        "scanned_at": scanned_at,
        "env_file": env_file,
    })

    # Parallel flow explanations
    flows = flow_data.get("flows", [])
    function_metrics = flow_data.get("function_metrics", {})
    flow_calls = [
        (
            "llm.flow.explain",
            {
                "flow": flow,
                "cluster_map": cluster_map_ref,
                "function_metrics": function_metrics,
                "env_file": env_file,
            },
        )
        for flow in flows
    ]
    flow_results = executor.invoke_parallel(flow_calls, max_workers=max(len(flows), 1))
    flow_summaries = [r["flow_summary"] for r in flow_results]

    ai_flow_result = executor.invoke("llm.flow.explanations.assemble", {
        "flow_summaries": flow_summaries,
        "repo_root": repo_root,
        "scanned_at": scanned_at,
        "env_file": env_file,
    })

    # Repo summary
    ai_repo_result = executor.invoke("llm.repo.summarize", {
        "repo_dossier": repo_dossier_ref,
        "ai_cluster_results": ai_cluster_result["ai_cluster_results"],
        "env_file": env_file,
    })

    return {
        "ai_file_explanations_path": ai_file_result["ai_file_explanations_path"],
        "ai_cluster_summaries_path": ai_cluster_result["ai_cluster_summaries_path"],
        "ai_flow_explanations_path": ai_flow_result["ai_flow_explanations_path"],
        "ai_repo_summary_path": ai_repo_result["ai_repo_summary_path"],
    }


# ---------------------------------------------------------------------------
# analysis_run_meaning_layer
# ---------------------------------------------------------------------------

def _analysis_run_meaning_layer(context: CapabilityContext) -> dict[str, Any]:
    """Run the full meaning layer pipeline (9 capabilities, ordered with parallelism)."""
    from reveng.coordination.execution import AgenticExecutor
    from reveng.analysis_engine.workflows.meaning.system_breakdown import run_system_breakdown

    executor = AgenticExecutor(context.runtime)
    base = {
        "enriched_file_breakdowns": context.require("enriched_file_breakdowns"),
        "relation_map": context.require("relation_map"),
        "cluster_map": context.require("cluster_map"),
        "flow_map": context.require("flow_map"),
    }
    return run_system_breakdown(executor, base)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(registry: CapabilityRegistry) -> None:
    registry.register(
        CapabilityDefinition(
            capability_id="analysis_extract_files",
            pack_id=PACK_ID,
            version="1",
            display_name="Extract Python Files (Parallel)",
            description="Extract all Python files from a scanned repo in parallel (6 workers).",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("scan_result", "repo_root", "extractor_workers"),
                output=("file_records",),
            ),
            implementation_logic=_analysis_extract_files,
            tags=("analysis", "pipeline"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="analysis_build_breakdowns",
            pack_id=PACK_ID,
            version="1",
            display_name="Build Breakdowns (Parallel)",
            description="Run file_breakdowns.enrich and clusters.build in parallel.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("file_breakdowns", "inventory", "relation_map"),
                output=("enriched_file_breakdowns", "enriched_path", "cluster_map", "cluster_map_path"),
            ),
            implementation_logic=_analysis_build_breakdowns,
            tags=("analysis", "pipeline"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="analysis_build_reports",
            pack_id=PACK_ID,
            version="1",
            display_name="Build Reports (Parallel)",
            description="Run repo_dossier, validation, and unknowns report builders in parallel.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("inventory", "relation_map", "file_breakdowns", "cluster_map", "flow_map", "enriched_file_breakdowns"),
                output=("repo_dossier", "repo_dossier_path", "validation_report", "validation_report_path", "error_count", "warning_count", "unknowns", "unknowns_path"),
            ),
            implementation_logic=_analysis_build_reports,
            tags=("analysis", "pipeline"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="analysis_narrate",
            pack_id=PACK_ID,
            version="1",
            display_name="Narrate Analysis with LLM",
            description="Run the full LLM narration pipeline over base analysis outputs.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("repo_root", "scanned_at", "cluster_map", "flow_map", "enriched_file_breakdowns", "repo_dossier", "env_file", "ai_file_workers", "ai_limit"),
                output=("ai_file_explanations_path", "ai_cluster_summaries_path", "ai_flow_explanations_path", "ai_repo_summary_path"),
            ),
            implementation_logic=_analysis_narrate,
            tags=("analysis", "pipeline", "llm"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="analysis_run_meaning_layer",
            pack_id=PACK_ID,
            version="1",
            display_name="Run Meaning Layer",
            description="Run all 9 meaning layer capabilities in dependency order.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("enriched_file_breakdowns", "relation_map", "cluster_map", "flow_map"),
                output=("ability_records", "ability_records_path", "ability_count",
                        "action_records", "action_records_path", "action_count",
                        "function_meaning_records", "function_meaning_records_path", "function_meaning_count",
                        "file_purpose_records", "file_purpose_records_path", "file_purpose_count",
                        "file_behavior_records", "file_behavior_records_path", "file_behavior_count",
                        "workflow_records", "workflow_records_path", "workflow_count",
                        "module_summary_records", "module_summary_records_path", "module_summary_count",
                        "subsystem_summary_records", "subsystem_summary_records_path",
                        "system_summary_path"),
            ),
            implementation_logic=_analysis_run_meaning_layer,
            tags=("analysis", "pipeline", "meaning"),
        )
    )
