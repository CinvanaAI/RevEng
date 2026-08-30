from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.integration.prompts import (
    SYSTEM_PROMPT,
    build_cluster_prompt,
    build_file_prompt,
    build_file_prompt_with_context,
    build_flow_prompt,
    build_repo_prompt,
)
from reveng.storage.paths import (
    ai_cluster_summaries_json_path,
    ai_file_explanations_json_path,
    ai_flow_explanations_json_path,
    ai_repo_summary_json_path,
)
from reveng.storage.writers.ai_cluster_writer import write_ai_cluster_summary_outputs
from reveng.storage.writers.ai_flow_writer import write_ai_flow_explanation_outputs
from reveng.storage.writers.ai_repo_writer import write_ai_repo_summary_outputs
from reveng.storage.writers.ai_writer import write_ai_file_explanation_outputs

PACK_ID = "reveng.pack.llm_narration"

FILE_EXPLANATIONS_KIND = "llm.file_explanations.v1"
CLUSTER_SUMMARIES_KIND = "llm.cluster_summaries.v1"
FLOW_EXPLANATIONS_KIND = "llm.flow_explanations.v1"
REPO_SUMMARY_KIND = "llm.repo_summary.v1"


def _json_views(path: Path, **extra: str | Path) -> dict[str, str | Path]:
    views: dict[str, str | Path] = {"markdown": path.with_suffix(".md")}
    views.update(extra)
    return views


# ---------------------------------------------------------------------------
# Shared normalization helpers (inlined from ai_interpreter.py)
# ---------------------------------------------------------------------------

REQUIRED_EXPLANATION_KEYS = [
    "path", "module_name",
    "defined_symbols_observed", "top_level_statements_observed",
    "calls_present_observed", "assignments_observed",
    "returns_observed", "raises_observed", "control_flow_observed",
    "visible_inputs_observed", "visible_outputs_observed",
    "visible_side_effects_observed",
    "resolved_inbound_relations_observed", "resolved_outbound_relations_observed",
    "unresolved_items_observed", "unknowns",
]

LIST_KEYS = [
    "defined_symbols_observed", "top_level_statements_observed",
    "calls_present_observed", "assignments_observed",
    "returns_observed", "raises_observed", "control_flow_observed",
    "visible_inputs_observed", "visible_outputs_observed",
    "visible_side_effects_observed",
    "resolved_inbound_relations_observed", "resolved_outbound_relations_observed",
    "unresolved_items_observed", "unknowns",
]

VALID_ARCHITECTURAL_ROLES = {
    "data_layer", "logic_layer", "io_layer", "entrypoint",
    "test_suite", "config_layer", "mixed", "unknown",
}

VALID_SYSTEM_TYPES = {
    "cli_tool", "library", "web_service", "script_collection",
    "data_pipeline", "test_suite", "mixed", "unknown",
}


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        normalized: list[str] = []
        for item in value:
            text = item.strip() if isinstance(item, str) else str(item).strip()
            if text:
                normalized.append(text)
        return normalized
    text = str(value).strip()
    return [text] if text else []


def _parse_json_response(raw: str, context_label: str) -> dict[str, Any]:
    """Strip markdown fences and parse JSON, raising RuntimeError on failure."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"LLM returned non-JSON for {context_label}: {text[:500]}"
        ) from exc


def _normalize_file_explanation(parsed: dict[str, Any], file_record: dict) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    normalized["path"] = str(parsed.get("path", file_record["path"])).strip() or file_record["path"]
    normalized["module_name"] = (
        str(parsed.get("module_name", file_record["module_name"])).strip()
        or file_record["module_name"]
    )
    for key in LIST_KEYS:
        normalized[key] = _normalize_list(parsed.get(key, []))
    for key in REQUIRED_EXPLANATION_KEYS:
        if key not in normalized:
            normalized[key] = [] if key in LIST_KEYS else ""
    return normalized


# ---------------------------------------------------------------------------
# Cluster context builder (inlined from ai_cluster_interpreter.py)
# ---------------------------------------------------------------------------

def _build_cluster_context(
    cluster: dict,
    cross_cluster_edges: list[dict],
    flow_map: dict,
    enriched_file_breakdowns: dict,
) -> dict[str, Any]:
    cluster_id = cluster["cluster_id"]
    obs = cluster["observed"]
    der = cluster["derived"]
    cluster_files: set[str] = set(obs["files"])

    file_index: dict[str, dict] = {
        fr["path"]: fr for fr in enriched_file_breakdowns.get("files", [])
    }
    file_signatures: list[dict] = []
    for fp in sorted(cluster_files):
        fr = file_index.get(fp)
        if fr is None or "parse_error" in fr:
            continue
        file_signatures.append({
            "path": fp,
            "defined_symbol_signatures": fr.get("defined_symbol_signatures", []),
            "unresolved_items": fr.get("unresolved_items", []),
        })

    outbound_counter: Counter[tuple[str, str]] = Counter()
    inbound_counter: Counter[tuple[str, str]] = Counter()
    for edge in cross_cluster_edges:
        if edge["source_cluster"] == cluster_id:
            outbound_counter[(edge["target_cluster"], edge["edge_type"])] += 1
        if edge["target_cluster"] == cluster_id:
            inbound_counter[(edge["source_cluster"], edge["edge_type"])] += 1

    outbound_edge_summary = [
        {"target_cluster": tgt, "edge_type": etype, "count": count}
        for (tgt, etype), count in sorted(outbound_counter.items())
    ]
    inbound_edge_summary = [
        {"source_cluster": src, "edge_type": etype, "count": count}
        for (src, etype), count in sorted(inbound_counter.items())
    ]

    flows = flow_map.get("flows", [])
    flow_ids_rooted_here: list[str] = []
    cross_cluster_flow_ids_passing_through: list[str] = []
    for flow in flows:
        if flow.get("root_cluster") == cluster_id:
            flow_ids_rooted_here.append(flow["flow_id"])
        elif cluster_id in flow.get("derived", {}).get("reachable_clusters", []):
            cross_cluster_flow_ids_passing_through.append(flow["flow_id"])

    hub_function_node_ids: list[str] = []
    for metric in flow_map.get("function_metrics", {}).values():
        if metric.get("file_path") in cluster_files and metric["derived"].get("is_hub"):
            hub_function_node_ids.append(metric["node_id"])
    hub_function_node_ids.sort()

    return {
        "cluster_id": cluster_id,
        "cluster_type": der["cluster_type"],
        "is_likely_entrypoint": der["is_likely_entrypoint"],
        "file_count": obs["file_count"],
        "files": sorted(cluster_files),
        "main_block_files": obs["main_block_files"],
        "internal_import_edge_count": obs["internal_import_edge_count"],
        "internal_call_edge_count": obs["internal_call_edge_count"],
        "outbound_cross_cluster_edge_count": der["outbound_cross_cluster_edge_count"],
        "inbound_cross_cluster_edge_count": der["inbound_cross_cluster_edge_count"],
        "connected_clusters": der["connected_clusters"],
        "file_signatures": file_signatures,
        "outbound_edge_summary": outbound_edge_summary,
        "inbound_edge_summary": inbound_edge_summary,
        "flow_ids_rooted_here": sorted(flow_ids_rooted_here),
        "cross_cluster_flow_ids_passing_through": sorted(cross_cluster_flow_ids_passing_through),
        "hub_function_node_ids": hub_function_node_ids,
    }


def _normalize_cluster_summary(
    parsed: Any,
    cluster_id: str,
    cluster_context: dict,
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {}

    observed: dict[str, Any] = {
        "file_count": cluster_context["file_count"],
        "files": cluster_context["files"],
        "main_block_files": cluster_context["main_block_files"],
        "internal_import_edge_count": cluster_context["internal_import_edge_count"],
        "internal_call_edge_count": cluster_context["internal_call_edge_count"],
        "outbound_cross_cluster_edge_count": cluster_context["outbound_cross_cluster_edge_count"],
        "inbound_cross_cluster_edge_count": cluster_context["inbound_cross_cluster_edge_count"],
        "connected_clusters": cluster_context["connected_clusters"],
        "cluster_type": cluster_context["cluster_type"],
        "is_likely_entrypoint": cluster_context["is_likely_entrypoint"],
        "flow_ids_rooted_here": cluster_context["flow_ids_rooted_here"],
        "cross_cluster_flow_ids_passing_through": cluster_context["cross_cluster_flow_ids_passing_through"],
        "hub_function_node_ids": cluster_context["hub_function_node_ids"],
    }

    role_raw = str(parsed.get("architectural_role", "")).strip()
    architectural_role = role_raw if role_raw in VALID_ARCHITECTURAL_ROLES else "unknown"

    derived: dict[str, Any] = {
        "purpose_statement": str(parsed.get("purpose_statement", "")).strip(),
        "responsibilities": _normalize_list(parsed.get("responsibilities", [])),
        "architectural_role": architectural_role,
        "key_dependencies_observed": _normalize_list(parsed.get("key_dependencies_observed", [])),
        "key_dependents_observed": _normalize_list(parsed.get("key_dependents_observed", [])),
    }

    return {
        "cluster_id": cluster_id,
        "observed": observed,
        "derived": derived,
        "unknown": _normalize_list(parsed.get("unknown", [])),
    }


# ---------------------------------------------------------------------------
# Flow context builder (inlined from ai_flow_interpreter.py)
# ---------------------------------------------------------------------------

def _build_flow_context(
    flow: dict,
    cluster_map: dict,
    function_metrics: dict,
) -> dict[str, Any]:
    cluster_type_map: dict[str, str] = {
        c["cluster_id"]: c["derived"]["cluster_type"]
        for c in cluster_map.get("clusters", [])
    }

    der = flow.get("derived", {})
    obs = flow.get("observed", {})
    flow_id = flow["flow_id"]

    hub_functions_in_flow = sorted(
        nid
        for nid, metric in function_metrics.items()
        if metric["derived"].get("is_hub")
        and flow_id in metric["derived"].get("appears_in_flows", [])
    )

    reachable_clusters = der.get("reachable_clusters", [])
    reachable_cluster_types = {
        cid: cluster_type_map.get(cid, "unknown") for cid in reachable_clusters
    }

    return {
        "flow_id": flow_id,
        "root_node_id": flow["root_node_id"],
        "root_file": flow.get("root_file", ""),
        "root_cluster": flow.get("root_cluster", ""),
        "root_cluster_type": cluster_type_map.get(flow.get("root_cluster", ""), "unknown"),
        "direct_callee_count": obs.get("direct_callee_count", 0),
        "direct_callees": obs.get("direct_callees", []),
        "total_call_edges_from_root": obs.get("total_call_edges_from_root", 0),
        "reachable_node_count": der.get("reachable_node_count", 0),
        "max_depth_reached": der.get("max_depth_reached", 0),
        "is_cross_cluster_flow": der.get("is_cross_cluster_flow", False),
        "reachable_clusters": reachable_clusters,
        "reachable_cluster_types": reachable_cluster_types,
        "cluster_crossings": der.get("cluster_crossings", []),
        "hub_functions_in_flow": hub_functions_in_flow,
        "unresolved_calls_in_flow": flow.get("unknown", []),
    }


def _normalize_flow_summary(
    parsed: Any,
    flow: dict,
    flow_context: dict,
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {}

    obs = flow.get("observed", {})
    der = flow.get("derived", {})

    observed: dict[str, Any] = {
        "direct_callee_count": obs.get("direct_callee_count", 0),
        "direct_callees": obs.get("direct_callees", []),
        "total_call_edges_from_root": obs.get("total_call_edges_from_root", 0),
        "reachable_node_count": der.get("reachable_node_count", 0),
        "max_depth_reached": der.get("max_depth_reached", 0),
        "is_cross_cluster_flow": der.get("is_cross_cluster_flow", False),
        "reachable_clusters": der.get("reachable_clusters", []),
        "cluster_crossings": der.get("cluster_crossings", []),
        "hub_functions_in_flow": flow_context["hub_functions_in_flow"],
    }

    derived: dict[str, Any] = {
        "flow_summary": str(parsed.get("flow_summary", "")).strip(),
        "entry_description": str(parsed.get("entry_description", "")).strip(),
        "key_steps": _normalize_list(parsed.get("key_steps", [])),
        "exit_description": str(parsed.get("exit_description", "")).strip(),
    }

    return {
        "flow_id": flow["flow_id"],
        "root_node_id": flow["root_node_id"],
        "root_file": flow.get("root_file", ""),
        "root_cluster": flow.get("root_cluster", ""),
        "observed": observed,
        "derived": derived,
        "unknown": _normalize_list(parsed.get("unknown", [])),
    }


# ---------------------------------------------------------------------------
# Repo context builder (inlined from ai_repo_interpreter.py)
# ---------------------------------------------------------------------------

def _build_repo_context(
    repo_dossier: dict,
    ai_cluster_results: dict,
) -> dict[str, Any]:
    arch = repo_dossier.get("architecture", {})

    cluster_purposes: list[dict[str, Any]] = []
    for result in ai_cluster_results.get("results", []):
        der = result.get("derived", {})
        obs = result.get("observed", {})
        cluster_purposes.append({
            "cluster_id": result["cluster_id"],
            "architectural_role": der.get("architectural_role", "unknown"),
            "purpose_statement": der.get("purpose_statement", ""),
            "responsibilities": der.get("responsibilities", []),
            "file_count": obs.get("file_count", 0),
            "is_likely_entrypoint": obs.get("is_likely_entrypoint", False),
        })

    entry_flows = arch.get("entry_flows", [])[:5]
    entry_flow_summaries = [
        {
            "flow_id": f["flow_id"],
            "root_cluster": f["root_cluster"],
            "reachable_node_count": f["reachable_node_count"],
            "is_cross_cluster_flow": f["is_cross_cluster_flow"],
            "reachable_cluster_count": f["reachable_cluster_count"],
        }
        for f in entry_flows
    ]

    return {
        "repo_root": repo_dossier.get("repo_root", ""),
        "file_count": repo_dossier.get("file_count", 0),
        "cluster_count": arch.get("cluster_count", 0),
        "flow_count": arch.get("flow_count", 0),
        "hub_function_count": arch.get("hub_function_count", 0),
        "cross_cluster_edge_count": arch.get("cross_cluster_edge_count", 0),
        "cluster_purposes": cluster_purposes,
        "entry_flows": entry_flow_summaries,
    }


def _normalize_repo_summary(
    parsed: Any,
    repo_dossier: dict,
    repo_context: dict,
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {}

    system_type_raw = str(parsed.get("system_type", "")).strip()
    system_type = system_type_raw if system_type_raw in VALID_SYSTEM_TYPES else "unknown"

    return {
        "repo_root": repo_dossier.get("repo_root", ""),
        "scanned_at": repo_dossier.get("scanned_at", ""),
        "observed": {
            "file_count": repo_dossier.get("file_count", 0),
            "cluster_count": repo_context["cluster_count"],
            "flow_count": repo_context["flow_count"],
            "hub_function_count": repo_context["hub_function_count"],
        },
        "derived": {
            "system_type": system_type,
            "primary_purpose": str(parsed.get("primary_purpose", "")).strip(),
            "repo_summary": str(parsed.get("repo_summary", "")).strip(),
            "key_capabilities": _normalize_list(parsed.get("key_capabilities", [])),
        },
        "unknown": _normalize_list(parsed.get("unknown", [])),
    }


# ---------------------------------------------------------------------------
# Capability handlers
# ---------------------------------------------------------------------------

def _require_provider(context: CapabilityContext) -> Any:
    provider = context.runtime.provider
    if provider is None:
        raise RuntimeError(
            "No provider configured. Set a ProviderClient on the host before running AI capabilities."
        )
    return provider


def _explain_file(context: CapabilityContext) -> dict[str, Any]:
    file_record = context.require("file_record")
    file_context = context.get("file_context") or None
    index = context.get("index", 0)

    provider = _require_provider(context)
    prompt = (
        build_file_prompt_with_context(file_record, file_context)
        if file_context
        else build_file_prompt(file_record)
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        raw = provider.chat(messages, response_format={"type": "json_object"})
        parsed = _parse_json_response(raw, file_record["path"])
        explanation = _normalize_file_explanation(parsed, file_record)
        warning = None
    except Exception as exc:
        explanation = _normalize_file_explanation({}, file_record)
        warning = f"{type(exc).__name__}: {exc}"

    return {
        "path": file_record["path"],
        "module_name": file_record["module_name"],
        "index": index,
        "explanation": explanation,
        "warning": warning,
    }


def _assemble_file_explanations(context: CapabilityContext) -> dict[str, Any]:
    path = ai_file_explanations_json_path(context.runtime.output_dir)
    views = _json_views(path)

    if context.cache_ready(path, output_name="ai_file_explanations"):
        ref = context.load_cached_json_artifact(
            FILE_EXPLANATIONS_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"ai_file_explanations": ref, "ai_file_explanations_path": str(path), "cached": True}

    results = sorted(list(context.require("explanation_results")), key=lambda item: item.get("path", ""))
    ai_results = {
        "repo_root": context.require("repo_root"),
        "scanned_at": context.require("scanned_at"),
        "requested_file_count": len(results),
        "env_file": context.get("env_file"),
        "results": results,
    }
    write_ai_file_explanation_outputs(ai_results, context.runtime.output_dir)
    ref = context.record_artifact(FILE_EXPLANATIONS_KIND, ai_results, path=path, views=views)
    return {"ai_file_explanations": ref, "ai_file_explanations_path": str(path), "cached": False}


def _summarize_cluster(context: CapabilityContext) -> dict[str, Any]:
    cluster = context.require("cluster")
    cross_cluster_edges = context.require("cross_cluster_edges")
    flow_map = context.read_input("flow_map")
    enriched = context.read_input("enriched_file_breakdowns")

    cluster_id = cluster["cluster_id"]
    cluster_context = _build_cluster_context(cluster, cross_cluster_edges, flow_map, enriched)

    provider = _require_provider(context)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_cluster_prompt(cluster_context)},
    ]
    try:
        raw = provider.chat(messages, response_format={"type": "json_object"})
        parsed = _parse_json_response(raw, cluster_id)
    except RuntimeError:
        parsed = {}
    summary = _normalize_cluster_summary(parsed, cluster_id, cluster_context)
    return {"cluster_summary": summary}


def _assemble_cluster_summaries(context: CapabilityContext) -> dict[str, Any]:
    path = ai_cluster_summaries_json_path(context.runtime.output_dir)
    views = _json_views(path)

    if context.cache_ready(path, output_name="ai_cluster_summaries"):
        ref = context.load_cached_json_artifact(
            CLUSTER_SUMMARIES_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {
            "ai_cluster_summaries": ref,
            "ai_cluster_summaries_path": str(path),
            "ai_cluster_results": context.runtime.artifacts.read(ref),
            "cached": True,
        }

    summaries = sorted(list(context.require("cluster_summaries")), key=lambda item: item.get("cluster_id", ""))
    ai_cluster_results = {
        "repo_root": context.require("repo_root"),
        "scanned_at": context.require("scanned_at"),
        "cluster_count": len(summaries),
        "env_file": context.get("env_file"),
        "results": summaries,
    }
    write_ai_cluster_summary_outputs(ai_cluster_results, context.runtime.output_dir)
    ref = context.record_artifact(CLUSTER_SUMMARIES_KIND, ai_cluster_results, path=path, views=views)
    return {
        "ai_cluster_summaries": ref,
        "ai_cluster_summaries_path": str(path),
        "ai_cluster_results": ai_cluster_results,
        "cached": False,
    }


def _explain_flow(context: CapabilityContext) -> dict[str, Any]:
    flow = context.require("flow")
    cluster_map = context.read_input("cluster_map")
    function_metrics = context.require("function_metrics")

    flow_context = _build_flow_context(flow, cluster_map, function_metrics)

    provider = _require_provider(context)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_flow_prompt(flow_context)},
    ]
    try:
        raw = provider.chat(messages, response_format={"type": "json_object"})
        parsed = _parse_json_response(raw, flow["flow_id"])
    except RuntimeError:
        parsed = {}
    summary = _normalize_flow_summary(parsed, flow, flow_context)
    return {"flow_summary": summary}


def _assemble_flow_explanations(context: CapabilityContext) -> dict[str, Any]:
    path = ai_flow_explanations_json_path(context.runtime.output_dir)
    views = _json_views(path, details_dir=context.runtime.output_dir / "ai_flow_breakdowns")

    if context.cache_ready(path, output_name="ai_flow_explanations"):
        ref = context.load_cached_json_artifact(
            FLOW_EXPLANATIONS_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"ai_flow_explanations": ref, "ai_flow_explanations_path": str(path), "cached": True}

    flow_summaries = sorted(list(context.require("flow_summaries")), key=lambda item: item.get("flow_id", ""))
    ai_flow_results = {
        "repo_root": context.require("repo_root"),
        "scanned_at": context.require("scanned_at"),
        "flow_count": len(flow_summaries),
        "env_file": context.get("env_file"),
        "results": flow_summaries,
    }
    write_ai_flow_explanation_outputs(ai_flow_results, context.runtime.output_dir)
    ref = context.record_artifact(FLOW_EXPLANATIONS_KIND, ai_flow_results, path=path, views=views)
    return {"ai_flow_explanations": ref, "ai_flow_explanations_path": str(path), "cached": False}


def _summarize_repo(context: CapabilityContext) -> dict[str, Any]:
    path = ai_repo_summary_json_path(context.runtime.output_dir)
    views = _json_views(path)

    if context.cache_ready(path, output_name="ai_repo_summary"):
        ref = context.load_cached_json_artifact(
            REPO_SUMMARY_KIND,
            path,
            views=views,
            metadata={"cached": True},
        )
        return {"ai_repo_summary": ref, "ai_repo_summary_path": str(path), "cached": True}

    repo_dossier = context.read_input("repo_dossier")
    ai_cluster_results = context.require("ai_cluster_results")
    repo_context = _build_repo_context(repo_dossier, ai_cluster_results)

    provider = _require_provider(context)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_repo_prompt(repo_context)},
    ]
    try:
        raw = provider.chat(messages, response_format={"type": "json_object"})
        parsed = _parse_json_response(raw, "repo")
    except RuntimeError:
        parsed = {}

    ai_repo_summary = _normalize_repo_summary(parsed, repo_dossier, repo_context)
    # Re-attach env_file for backward-compat output key
    env_file = context.get("env_file")
    if env_file is not None:
        ai_repo_summary = dict(ai_repo_summary)
        env_path = Path(env_file).expanduser().resolve()
        ai_repo_summary["env_file"] = str(env_path)

    write_ai_repo_summary_outputs(ai_repo_summary, context.runtime.output_dir)
    ref = context.record_artifact(REPO_SUMMARY_KIND, ai_repo_summary, path=path, views=views)
    return {"ai_repo_summary": ref, "ai_repo_summary_path": str(path), "cached": False}


def register(registry: CapabilityRegistry) -> None:
    registry.register(
        CapabilityDefinition(
            capability_id="llm.file.explain",
            pack_id=PACK_ID,
            version="1",
            display_name="Explain File with LLM",
            description="Explain one file record with an LLM.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("file_record", "file_context", "repo_root", "env_file", "index"),
                output=("path", "module_name", "index", "explanation", "warning"),
            ),
            implementation_logic=_explain_file,
            tags=("llm", "file"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="llm.file.explanations.assemble",
            pack_id=PACK_ID,
            version="1",
            display_name="Assemble File Explanations",
            description="Assemble file explanations into durable outputs.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("explanation_results", "repo_root", "scanned_at", "env_file"),
                output=("ai_file_explanations", "ai_file_explanations_path", "cached"),
            ),
            implementation_logic=_assemble_file_explanations,
            tags=("llm", "file"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="llm.cluster.summarize",
            pack_id=PACK_ID,
            version="1",
            display_name="Summarize Cluster with LLM",
            description="Summarize one cluster with an LLM.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("cluster", "cross_cluster_edges", "flow_map", "enriched_file_breakdowns", "env_file"),
                output=("cluster_summary",),
            ),
            implementation_logic=_summarize_cluster,
            tags=("llm", "cluster"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="llm.cluster.summaries.assemble",
            pack_id=PACK_ID,
            version="1",
            display_name="Assemble Cluster Summaries",
            description="Assemble cluster summaries into durable outputs.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("cluster_summaries", "repo_root", "scanned_at", "env_file"),
                output=("ai_cluster_summaries", "ai_cluster_summaries_path", "ai_cluster_results", "cached"),
            ),
            implementation_logic=_assemble_cluster_summaries,
            tags=("llm", "cluster"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="llm.flow.explain",
            pack_id=PACK_ID,
            version="1",
            display_name="Explain Flow with LLM",
            description="Explain one flow with an LLM.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("flow", "cluster_map", "function_metrics", "env_file"),
                output=("flow_summary",),
            ),
            implementation_logic=_explain_flow,
            tags=("llm", "flow"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="llm.flow.explanations.assemble",
            pack_id=PACK_ID,
            version="1",
            display_name="Assemble Flow Explanations",
            description="Assemble flow explanations into durable outputs.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("flow_summaries", "repo_root", "scanned_at", "env_file"),
                output=("ai_flow_explanations", "ai_flow_explanations_path", "cached"),
            ),
            implementation_logic=_assemble_flow_explanations,
            tags=("llm", "flow"),
        )
    )
    registry.register(
        CapabilityDefinition(
            capability_id="llm.repo.summarize",
            pack_id=PACK_ID,
            version="1",
            display_name="Summarize Repository with LLM",
            description="Summarize the repository with an LLM.",
            capability_type="function",
            contract=CapabilityContract(
                inputs=("repo_dossier", "ai_cluster_results", "env_file"),
                output=("ai_repo_summary", "ai_repo_summary_path", "cached"),
            ),
            implementation_logic=_summarize_repo,
            tags=("llm", "repo"),
        )
    )
