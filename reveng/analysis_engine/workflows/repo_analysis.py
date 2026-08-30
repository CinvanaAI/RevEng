from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reveng.framework import WorkflowDefinition, WorkflowRegistry, WorkflowRuntime
from reveng.analysis_engine.packs import llm_narration, python_static
from reveng.storage.paths import (
    ai_cluster_summaries_json_path,
    ai_file_explanations_json_path,
    ai_flow_explanations_json_path,
    inventory_json_path,
)

DEFAULT_EXTRACTOR_WORKERS = 6
DEFAULT_AI_FILE_WORKERS = 10

WORKFLOW_ID = "reveng.workflow.repo_analysis"
WORKFLOW_WITH_AI_ID = "reveng.workflow.repo_analysis.with_ai"


def _tool_allowed_file_paths(inputs: dict[str, Any], capability_id: str) -> list[str] | None:
    visibility = inputs.get("agent_keycard_visibility")
    if not isinstance(visibility, dict):
        return None
    tool_paths = visibility.get("tool_allowed_file_paths", {})
    if isinstance(tool_paths, dict):
        value = tool_paths.get(capability_id)
        if isinstance(value, list):
            return list(value)
    return None


def _invoke_parallel(
    runtime: WorkflowRuntime,
    calls: list[tuple[str, dict[str, Any]]],
    *,
    max_workers: int,
) -> list[dict[str, Any]]:
    if not calls:
        return []

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(runtime.invoke, capability_id, inputs)
            for capability_id, inputs in calls
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return results


def _run_base_analysis(runtime: WorkflowRuntime, inputs: dict[str, Any]) -> dict[str, Any]:
    extractor_workers = int(inputs.get("extractor_workers", DEFAULT_EXTRACTOR_WORKERS))

    scan_result = runtime.invoke(
        "python.scan_repo",
        {
            "repo_path": inputs["repo_path"],
            "visible_file_paths": _tool_allowed_file_paths(inputs, "python.scan_repo"),
        },
    )
    scan_data = runtime.read_input(scan_result["scan_result"])
    repo_root = scan_data["repo_root"]
    file_paths = scan_data["file_paths"]
    scanned_at = datetime.now(UTC).isoformat()

    inventory_path = inventory_json_path(runtime.output_dir)
    if runtime.cache.is_ready(
        inventory_path,
        capability_id="python.inventory.assemble",
        output_name="inventory",
        inputs={"repo_root": repo_root},
    ):
        inventory_result = runtime.invoke(
            "python.inventory.assemble",
            {
                "repo_root": repo_root,
                "file_records": [],
                "scanned_at": scanned_at,
            },
        )
    else:
        extract_results = _invoke_parallel(
            runtime,
            [
                (
                    "python.extract_file",
                    {
                        "repo_root": repo_root,
                        "file_path": file_path,
                        "allowed_file_paths": _tool_allowed_file_paths(inputs, "python.extract_file"),
                    },
                )
                for file_path in file_paths
            ],
            max_workers=extractor_workers,
        )
        file_records = [runtime.read_input(item["file_record"]) for item in extract_results]
        file_records.sort(key=lambda item: item.get("path", ""))
        inventory_result = runtime.invoke(
            "python.inventory.assemble",
            {
                "repo_root": repo_root,
                "file_records": file_records,
                "scanned_at": scanned_at,
            },
        )

    inventory = inventory_result["inventory"]
    relation_result = runtime.invoke("python.relations.build", {"inventory": inventory})
    file_breakdown_result = runtime.invoke(
        "python.file_breakdowns.build",
        {
            "inventory": inventory,
            "relation_map": relation_result["relation_map"],
        },
    )

    parallel_stage_results = _invoke_parallel(
        runtime,
        [
            (
                "python.file_breakdowns.enrich",
                {"file_breakdowns": file_breakdown_result["file_breakdowns"]},
            ),
            (
                "python.clusters.build",
                {
                    "inventory": inventory,
                    "relation_map": relation_result["relation_map"],
                },
            ),
        ],
        max_workers=2,
    )

    enrich_result = next(item for item in parallel_stage_results if "enriched_file_breakdowns" in item)
    cluster_result = next(item for item in parallel_stage_results if "cluster_map" in item)

    flow_result = runtime.invoke(
        "python.flows.build",
        {
            "inventory": inventory,
            "relation_map": relation_result["relation_map"],
            "cluster_map": cluster_result["cluster_map"],
        },
    )

    reporting_results = _invoke_parallel(
        runtime,
        [
            (
                "report.repo_dossier.build",
                {
                    "inventory": inventory,
                    "relation_map": relation_result["relation_map"],
                    "file_breakdowns": file_breakdown_result["file_breakdowns"],
                    "cluster_map": cluster_result["cluster_map"],
                    "flow_map": flow_result["flow_map"],
                },
            ),
            (
                "report.validate",
                {
                    "inventory": inventory,
                    "relation_map": relation_result["relation_map"],
                    "file_breakdowns": file_breakdown_result["file_breakdowns"],
                    "flow_map": flow_result["flow_map"],
                },
            ),
            (
                "report.unknowns.build",
                {
                    "inventory": inventory,
                    "relation_map": relation_result["relation_map"],
                    "cluster_map": cluster_result["cluster_map"],
                    "flow_map": flow_result["flow_map"],
                    "enriched_file_breakdowns": enrich_result["enriched_file_breakdowns"],
                },
            ),
        ],
        max_workers=3,
    )

    repo_dossier_result = next(item for item in reporting_results if "repo_dossier" in item)
    validation_result = next(item for item in reporting_results if "validation_report" in item)
    unknowns_result = next(item for item in reporting_results if "unknowns" in item)

    return {
        "repo_root": repo_root,
        "scanned_at": scanned_at,
        "file_count": len(file_paths),
        "inventory": inventory,
        "inventory_path": inventory_result["inventory_path"],
        "relation_map": relation_result["relation_map"],
        "relation_map_path": relation_result["relation_map_path"],
        "file_breakdowns": file_breakdown_result["file_breakdowns"],
        "file_breakdowns_path": file_breakdown_result["file_breakdowns_path"],
        "enriched_file_breakdowns": enrich_result["enriched_file_breakdowns"],
        "enriched_path": enrich_result["enriched_path"],
        "cluster_map": cluster_result["cluster_map"],
        "cluster_map_path": cluster_result["cluster_map_path"],
        "flow_map": flow_result["flow_map"],
        "flow_map_path": flow_result["flow_map_path"],
        "repo_dossier": repo_dossier_result["repo_dossier"],
        "repo_dossier_path": repo_dossier_result["repo_dossier_path"],
        "validation_report": validation_result["validation_report"],
        "validation_report_path": validation_result["validation_report_path"],
        "unknowns": unknowns_result["unknowns"],
        "unknowns_path": unknowns_result["unknowns_path"],
        "error_count": validation_result["error_count"],
        "warning_count": validation_result["warning_count"],
    }


def _finalize_outputs(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "inventory_path": result["inventory_path"],
        "relation_map_path": result["relation_map_path"],
        "file_breakdowns_path": result["file_breakdowns_path"],
        "enriched_path": result["enriched_path"],
        "cluster_map_path": result["cluster_map_path"],
        "flow_map_path": result["flow_map_path"],
        "repo_dossier_path": result["repo_dossier_path"],
        "validation_report_path": result["validation_report_path"],
        "unknowns_path": result["unknowns_path"],
        "file_count": result["file_count"],
        "error_count": result["error_count"],
        "warning_count": result["warning_count"],
    }


def _run_analysis(runtime: WorkflowRuntime, inputs: dict[str, Any]) -> dict[str, Any]:
    return _finalize_outputs(_run_base_analysis(runtime, inputs))


def _run_analysis_with_ai(runtime: WorkflowRuntime, inputs: dict[str, Any]) -> dict[str, Any]:
    result = _run_base_analysis(runtime, inputs)
    ai_file_workers = int(inputs.get("ai_file_workers", DEFAULT_AI_FILE_WORKERS))
    env_file = inputs.get("env_file", ".env")
    env_file_resolved = str(Path(env_file).expanduser().resolve())
    ai_limit = inputs.get("ai_limit")

    cluster_data = runtime.read_input(result["cluster_map"])
    flow_data = runtime.read_input(result["flow_map"])
    enriched_data = runtime.read_input(result["enriched_file_breakdowns"])

    ctx_result = runtime.invoke("python.context.per_file.build", {
        "cluster_map": result["cluster_map"],
        "flow_map": result["flow_map"],
    })
    per_file_ctx: dict = ctx_result["per_file_context"]

    ai_file_path = ai_file_explanations_json_path(runtime.output_dir)
    if runtime.cache.is_ready(
        ai_file_path,
        capability_id="llm.file.explanations.assemble",
        output_name="ai_file_explanations",
        inputs={"repo_root": result["repo_root"]},
    ):
        ai_file_result = runtime.invoke(
            "llm.file.explanations.assemble",
            {
                "explanation_results": [],
                "repo_root": result["repo_root"],
                "scanned_at": result["scanned_at"],
                "env_file": env_file_resolved,
            },
        )
    else:
        files_to_explain = [
            item for item in enriched_data.get("files", []) if "parse_error" not in item
        ]
        if ai_limit is not None:
            files_to_explain = files_to_explain[:ai_limit]

        explain_results = _invoke_parallel(
            runtime,
            [
                (
                    "llm.file.explain",
                    {
                        "file_record": file_record,
                        "file_context": per_file_ctx.get(file_record["path"]),
                        "repo_root": result["repo_root"],
                        "env_file": env_file,
                        "index": index,
                    },
                )
                for index, file_record in enumerate(files_to_explain, start=1)
            ],
            max_workers=ai_file_workers,
        )
        explanation_results = []
        for item in explain_results:
            if item.get("warning"):
                print(f"WARNING: File AI failed for {item['path']}: {item['warning']}")
            explanation_results.append(item)
        ai_file_result = runtime.invoke(
            "llm.file.explanations.assemble",
            {
                "explanation_results": explanation_results,
                "repo_root": result["repo_root"],
                "scanned_at": result["scanned_at"],
                "env_file": env_file_resolved,
            },
        )

    ai_cluster_path = ai_cluster_summaries_json_path(runtime.output_dir)
    ai_flow_path = ai_flow_explanations_json_path(runtime.output_dir)

    if runtime.cache.is_ready(
        ai_cluster_path,
        capability_id="llm.cluster.summaries.assemble",
        output_name="ai_cluster_summaries",
        inputs={"repo_root": result["repo_root"]},
    ):
        ai_cluster_result = runtime.invoke(
            "llm.cluster.summaries.assemble",
            {
                "cluster_summaries": [],
                "repo_root": result["repo_root"],
                "scanned_at": result["scanned_at"],
                "env_file": env_file_resolved,
            },
        )
    else:
        cluster_results = _invoke_parallel(
            runtime,
            [
                (
                    "llm.cluster.summarize",
                    {
                        "cluster": cluster,
                        "cross_cluster_edges": cluster_data.get("cross_cluster_edges", []),
                        "flow_map": result["flow_map"],
                        "enriched_file_breakdowns": result["enriched_file_breakdowns"],
                        "env_file": env_file,
                    },
                )
                for cluster in cluster_data.get("clusters", [])
            ],
            max_workers=max(len(cluster_data.get("clusters", [])), 1),
        )
        ai_cluster_result = runtime.invoke(
            "llm.cluster.summaries.assemble",
            {
                "cluster_summaries": [item["cluster_summary"] for item in cluster_results],
                "repo_root": result["repo_root"],
                "scanned_at": result["scanned_at"],
                "env_file": env_file_resolved,
            },
        )

    if runtime.cache.is_ready(
        ai_flow_path,
        capability_id="llm.flow.explanations.assemble",
        output_name="ai_flow_explanations",
        inputs={"repo_root": result["repo_root"]},
    ):
        ai_flow_result = runtime.invoke(
            "llm.flow.explanations.assemble",
            {
                "flow_summaries": [],
                "repo_root": result["repo_root"],
                "scanned_at": result["scanned_at"],
                "env_file": env_file_resolved,
            },
        )
    else:
        flow_results = _invoke_parallel(
            runtime,
            [
                (
                    "llm.flow.explain",
                    {
                        "flow": flow,
                        "cluster_map": result["cluster_map"],
                        "function_metrics": flow_data.get("function_metrics", {}),
                        "env_file": env_file,
                    },
                )
                for flow in flow_data.get("flows", [])
            ],
            max_workers=max(len(flow_data.get("flows", [])), 1),
        )
        ai_flow_result = runtime.invoke(
            "llm.flow.explanations.assemble",
            {
                "flow_summaries": [item["flow_summary"] for item in flow_results],
                "repo_root": result["repo_root"],
                "scanned_at": result["scanned_at"],
                "env_file": env_file_resolved,
            },
        )

    ai_repo_result = runtime.invoke(
        "llm.repo.summarize",
        {
            "repo_dossier": result["repo_dossier"],
            "ai_cluster_results": ai_cluster_result["ai_cluster_results"],
            "env_file": env_file,
        },
    )

    outputs = _finalize_outputs(result)
    outputs.update(
        {
            "ai_file_explanations_path": ai_file_result["ai_file_explanations_path"],
            "ai_cluster_summaries_path": ai_cluster_result["ai_cluster_summaries_path"],
            "ai_flow_explanations_path": ai_flow_result["ai_flow_explanations_path"],
            "ai_repo_summary_path": ai_repo_result["ai_repo_summary_path"],
            "env_file_resolved": env_file_resolved,
        }
    )
    return outputs


def register(registry: WorkflowRegistry) -> None:
    registry.register(
        WorkflowDefinition(
            workflow_id=WORKFLOW_ID,
            description="Default deterministic Python repo-analysis workflow.",
            handler=_run_analysis,
        )
    )
    registry.register(
        WorkflowDefinition(
            workflow_id=WORKFLOW_WITH_AI_ID,
            description="Default Python repo-analysis workflow with LLM narration.",
            handler=_run_analysis_with_ai,
        )
    )


# Public alias — used by layered_breakdown.py to run base analysis without re-registering
run_base_analysis = _run_base_analysis
