"""Integration Layer — LLM prompt templates for outbound API calls.

These are protocol adaptation artifacts: they format domain data into
the wire shape expected by the external LLM endpoint.
"""
from __future__ import annotations

import json


SYSTEM_PROMPT = """You are a strict reverse-engineering assistant.

You will be given a structured file breakdown generated from static analysis.
You must explain only what is directly supported by the provided record.

Hard rules:
- Do not invent missing behavior.
- Do not claim that a function runs, is called, or is used unless the provided record explicitly shows that relation.
- Do not claim workflows unless directly supported by the provided record.
- Do not use words like "likely", "probably", "appears", or "seems".
- Do not turn definitions into runtime facts.
- Keep statements direct, concrete, and limited to the record.
- Return valid JSON only.

Important framing:
- "Defined in file" is allowed.
- "Call present in file" is allowed.
- "Resolved inbound call edge" is allowed.
- "Resolved outbound call edge" is allowed.
- "Unresolved call recorded" is allowed.
- "Unknown from provided record" is allowed.
- "This function is called to do X" is NOT allowed unless the record explicitly proves it.
"""

JSON_SCHEMA_DESCRIPTION = {
    "path": "string",
    "module_name": "string",
    "defined_symbols_observed": [
        "string"
    ],
    "top_level_statements_observed": [
        "string"
    ],
    "calls_present_observed": [
        "string"
    ],
    "assignments_observed": [
        "string"
    ],
    "returns_observed": [
        "string"
    ],
    "raises_observed": [
        "string"
    ],
    "control_flow_observed": [
        "string"
    ],
    "visible_inputs_observed": [
        "string"
    ],
    "visible_outputs_observed": [
        "string"
    ],
    "visible_side_effects_observed": [
        "string"
    ],
    "resolved_inbound_relations_observed": [
        "string"
    ],
    "resolved_outbound_relations_observed": [
        "string"
    ],
    "unresolved_items_observed": [
        "string"
    ],
    "unknowns": [
        "string"
    ],
}


CLUSTER_JSON_SCHEMA_DESCRIPTION = {
    "purpose_statement": "string — one sentence, observed artifact language only",
    "responsibilities": ["string"],
    "architectural_role": (
        "string — exactly one of: data_layer, logic_layer, io_layer, "
        "entrypoint, test_suite, config_layer, mixed, unknown"
    ),
    "key_dependencies_observed": ["string"],
    "key_dependents_observed": ["string"],
    "unknown": ["string"],
}


# Fields excluded from AI prompts — redundant with cleaner fields or too large
_EXCLUDED_FILE_RECORD_FIELDS = {
    "all_inbound_edges",       # redundant with inbound_call_edges
    "all_outbound_edges",      # redundant with outbound_call_edges + outbound_import_edges
    "outbound_contains_edges", # redundant with defined_symbols
    "calls",                   # raw AST calls; outbound_call_edges is the resolved version
    "decorators",              # rarely useful for AI explanation
}

_LIST_FIELD_CAPS = {
    "assignments": 30,
    "control_flow": 30,
    "returns": 30,
    "raises": 20,
    "outbound_call_edges": 40,
    "inbound_call_edges": 30,
    "unresolved_calls": 25,
    "unresolved_items": 25,
    "observed_inputs": 20,
    "observed_outputs": 20,
    "observed_side_effects": 20,
}


def _slim_file_record(file_record: dict) -> dict:
    """Return a copy of file_record with redundant fields removed and large lists capped."""
    slim = {}
    for key, value in file_record.items():
        if key in _EXCLUDED_FILE_RECORD_FIELDS:
            continue
        cap = _LIST_FIELD_CAPS.get(key)
        if cap is not None and isinstance(value, list) and len(value) > cap:
            slim[key] = value[:cap]
            slim[f"{key}__truncated"] = len(value) - cap
        else:
            slim[key] = value
    return slim


def build_file_prompt(file_record: dict) -> str:
    payload = {
        "task": (
            "Explain this file from the provided structured breakdown only. "
            "Use only observed artifact language. "
            "Do not convert definitions into runtime claims."
        ),
        "required_output_schema": JSON_SCHEMA_DESCRIPTION,
        "file_record": _slim_file_record(file_record),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_file_prompt_with_context(file_record: dict, file_context: dict) -> str:
    payload: dict = {
        "task": (
            "Explain this file from the provided structured breakdown only. "
            "Use only observed artifact language. "
            "Do not convert definitions into runtime claims. "
            "Use structural_context fields (if present) to note cluster membership "
            "and flow participation using observed artifact language only."
        ),
        "required_output_schema": JSON_SCHEMA_DESCRIPTION,
        "file_record": _slim_file_record(file_record),
    }
    if file_context:
        # Exclude cluster_internal_call_edge_count — cluster aggregate, not per-file useful
        ctx = {k: v for k, v in file_context.items() if k != "cluster_internal_call_edge_count"}
        payload["structural_context"] = ctx
    return json.dumps(payload, indent=2, ensure_ascii=False)


FLOW_JSON_SCHEMA_DESCRIPTION = {
    "flow_summary": "string — one sentence describing what this flow does, observed artifact language only",
    "entry_description": "string — what function or condition starts this flow, from the record only",
    "key_steps": ["string — notable steps in call order, named from node IDs or cluster names in the record"],
    "exit_description": "string — where the flow terminates or what it produces, from the record only",
    "unknown": ["string"],
}

REPO_JSON_SCHEMA_DESCRIPTION = {
    "system_type": (
        "string — exactly one of: cli_tool, library, web_service, script_collection, "
        "data_pipeline, test_suite, mixed, unknown"
    ),
    "primary_purpose": "string — one sentence describing the repo's primary function, observed language only",
    "repo_summary": "string — 2-3 sentences describing what the repo does as a whole, observed language only",
    "key_capabilities": ["string — capabilities directly evidenced by cluster purposes or flow records"],
    "unknown": ["string"],
}


def build_flow_prompt(flow_context: dict) -> str:
    payload = {
        "task": (
            "Summarise this call flow from the provided structural data only. "
            "Use observed artifact language. Do not invent behavior not present in the record. "
            "key_steps must reference only node IDs, cluster IDs, or file paths that appear "
            "in the provided flow_context."
        ),
        "required_output_schema": FLOW_JSON_SCHEMA_DESCRIPTION,
        "flow_context": flow_context,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_repo_prompt(repo_context: dict) -> str:
    payload = {
        "task": (
            "Summarise this repository from the provided structural data only. "
            "Use observed artifact language. Do not invent behavior not present in the record. "
            "system_type must be exactly one of: cli_tool, library, web_service, "
            "script_collection, data_pipeline, test_suite, mixed, unknown. "
            "key_capabilities must be directly evidenced by cluster purposes or flow records "
            "in the provided context."
        ),
        "required_output_schema": REPO_JSON_SCHEMA_DESCRIPTION,
        "repo_context": repo_context,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_cluster_prompt(cluster_context: dict) -> str:
    payload = {
        "task": (
            "Summarise this software cluster from the provided structural data only. "
            "Use observed artifact language. Do not invent behavior not present in the record. "
            "architectural_role must be exactly one of: data_layer, logic_layer, io_layer, "
            "entrypoint, test_suite, config_layer, mixed, unknown. "
            "key_dependencies_observed and key_dependents_observed must name only clusters "
            "that appear in outbound_edge_summary or inbound_edge_summary respectively."
        ),
        "required_output_schema": CLUSTER_JSON_SCHEMA_DESCRIPTION,
        "cluster_context": {
            k: v for k, v in cluster_context.items() if k != "files"
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
