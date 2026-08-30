"""WorkflowMeaningAgent — derives WorkflowRecords from ActionRecords + flow_map.

For each flow in the flow_map, collects ActionRecords whose function_scope
appears in the flow's reachable nodes and builds a WorkflowRecord.

Fallback: when direct_callees is empty (e.g. cross-package imports unresolved
by the base analysis), the enriched call records for the entry function are
used to discover callee names via call-name matching against scope_actions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reveng.analysis_engine.agentic.tasks.functions import _build_file_index, _BUILTIN_NAMES, _generate_id, _make_derivation
from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.analysis_engine.meaning.aggregation import aggregate_dimensions
from reveng.analysis_engine.meaning.confidence import ConfidenceLevel
from reveng.analysis_engine.meaning.derivation import DerivationBasis
from reveng.analysis_engine.meaning.layers import LayerID
from reveng.analysis_engine.meaning.records import WorkflowRecord, to_dict

PACK_ID = "reveng.pack.meaning_layer"
KIND = "meaning.workflow_records.v1"


def _files_match(a: str, b: str) -> bool:
    """True if two relative file paths refer to the same file despite prefix differences."""
    a = a.replace("\\", "/")
    b = b.replace("\\", "/")
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def _callee_names_from_enriched(
    entry_file: str,
    entry_func: str,
    enriched: dict[str, Any],
) -> set[str]:
    """Extract bare callee names called from entry_func in entry_file.

    Used as a fallback when the flow_map direct_callees list is empty —
    e.g. when cross-package imports could not be resolved by the base analysis.
    """
    file_index = _build_file_index(enriched)
    file_record = file_index.get(entry_file, {})
    names: set[str] = set()
    for call in file_record.get("calls", []):
        scope = call.get("enclosing_scope", "")
        if not (scope.endswith(":" + entry_func) or scope == entry_func):
            continue
        called = call.get("called_name", "")
        if called and "." not in called and called not in _BUILTIN_NAMES:
            names.add(called)
    return names


def _build_caller_callees(enriched: dict[str, Any]) -> dict[str, set[str]]:
    """Pre-compute basename(scope) -> set of bare callee names, across all files.

    Extracted once before the flow loop so the map is not rebuilt per-flow.
    """
    caller_callees: dict[str, set[str]] = {}
    for file_record in _build_file_index(enriched).values():
        for call in file_record.get("calls", []):
            enc_scope = call.get("enclosing_scope", "")
            callee = call.get("called_name", "")
            if not callee or "." in callee or callee in _BUILTIN_NAMES:
                continue
            # Extract basename: "module > function:run_report" → "run_report"
            caller = enc_scope.split(":")[-1] if ":" in enc_scope else enc_scope
            if caller:
                caller_callees.setdefault(caller, set()).add(callee)
    return caller_callees


def _expand_node_names_bfs(
    initial_names: set[str],
    scope_actions: dict[str, list[dict[str, Any]]],
    caller_callees: dict[str, set[str]],
    *,
    max_depth: int = 2,
) -> set[str]:
    """BFS expansion through zero-action wrapper chains, bounded by max_depth.

    Handles multi-hop chains: A→B→C→D where only D has actions.
    Each hop only expands names that have *no* direct action matches, so names
    that already have actions are never expanded further (preventing inflation).

    Early termination when no new names are found at a given depth.
    Visited set prevents re-expanding the same name across hops (prevents cycles).
    """
    all_names = set(initial_names)
    frontier = set(initial_names)
    visited: set[str] = set()

    for _ in range(max_depth):
        new_frontier: set[str] = set()
        for name in frontier:
            if name in visited:
                continue
            visited.add(name)
            has_actions = any(s.endswith(":" + name) or s == name for s in scope_actions)
            if not has_actions:
                for callee in caller_callees.get(name, ()):
                    if callee not in all_names:
                        new_frontier.add(callee)
        if not new_frontier:
            break
        all_names.update(new_frontier)
        frontier = new_frontier

    return all_names


def _node_id_to_name_and_file(nid: str) -> tuple[str, str]:
    """Extract (function_name, file_path) from a node_id string.

    Format: "kind:file_path:scope:name" — uses split(":", 2) then rsplit to
    handle scopes containing colons (e.g. "module > class:Foo").
    """
    parts = nid.split(":", 2)
    if len(parts) >= 3:
        return parts[2].rsplit(":", 1)[-1] if ":" in parts[2] else parts[2], parts[1]
    return parts[-1], ""


def _build_file_to_node_ids(flow_map: dict[str, Any]) -> dict[str, list[str]]:
    """Build file_path -> [node_ids] from flow_map function_metrics."""
    result: dict[str, list[str]] = {}
    for nid, metrics in flow_map.get("function_metrics", {}).items():
        fp = metrics.get("file_path", "")
        if fp:
            result.setdefault(fp, []).append(nid)
    return result


def _derive_workflows(
    actions: list[dict[str, Any]],
    flow_map: dict[str, Any],
    enriched: dict[str, Any] | None = None,
) -> list[WorkflowRecord]:
    records: list[WorkflowRecord] = []

    # Build a lookup: function_scope -> list of action dicts
    scope_actions: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        scope = action.get("function_scope", "")
        scope_actions.setdefault(scope, []).append(action)

    flows = flow_map.get("flows", []) if isinstance(flow_map, dict) else []

    # Pre-build caller_callees once — shared across all flows
    caller_callees = _build_caller_callees(enriched) if enriched else {}

    # Phase 6: file-sibling index — file_path -> [node_ids] for register-pattern extension
    file_to_node_ids = _build_file_to_node_ids(flow_map)

    # Phase 6: set of files that have at least one action record (hard bound)
    files_with_actions: set[str] = {
        action.get("file_path", "")
        for action_list in scope_actions.values()
        for action in action_list
        if action.get("file_path")
    }

    for flow in flows:
        flow_id = flow.get("flow_id", "")
        entry_point = flow.get("root_file", "")
        root_node_id = flow.get("root_node_id", "")
        flow_type = flow.get("derived", {}).get("flow_type", "")
        direct_callees = flow.get("observed", {}).get("direct_callees", [])
        # Use the full BFS-reachable set when available (flow_builder computes up to
        # MAX_FLOW_DEPTH=8 hops); fall back to direct_callees for old cached flow maps.
        reachable_node_ids = flow.get("derived", {}).get("reachable_node_ids") or direct_callees
        all_node_ids = ([root_node_id] if root_node_id else []) + reachable_node_ids

        # Extract function names AND file paths from node_ids.
        # Format: "kind:file_path:scope:name" — use split(":", 2) + rsplit to handle
        # scopes that themselves contain colons (e.g. "module > class:Foo").
        node_names: set[str] = set()
        node_file_map: dict[str, str] = {}  # name → file_path (for file-qualified matching)
        for nid in all_node_ids:
            if not nid:
                continue
            name_from_nid, file_from_nid = _node_id_to_name_and_file(nid)
            if name_from_nid:
                node_names.add(name_from_nid)
                if file_from_nid:
                    node_file_map[name_from_nid] = file_from_nid

        # Fallback: when direct_callees is empty, discover callees from enriched call records
        entry_func = root_node_id.split(":")[-1] if root_node_id else ""
        if not direct_callees and enriched and entry_point and entry_func:
            fallback_names = _callee_names_from_enriched(entry_point, entry_func, enriched)
            node_names.update(fallback_names)

        # Multi-hop BFS expansion: for any node name with no direct actions, include its
        # callees (up to max_depth hops). Handles chains A→B→C→D where only D has actions.
        if caller_callees:
            node_names = _expand_node_names_bfs(node_names, scope_actions, caller_callees)

        # Phase 6: file-sibling flow extension (entry_point flows only).
        # When a 'register' node is BFS-reachable, include other callables from its file
        # if that file already has action records. Tracks sibling names separately so
        # provenance can be reported in the derivation note.
        sibling_names: set[str] = set()
        sibling_files: list[str] = []
        if flow_type == "entry_point":
            # Find files containing reachable 'register' nodes
            register_files: set[str] = set()
            for nid in all_node_ids:
                name_part, file_part = _node_id_to_name_and_file(nid)
                if name_part == "register" and file_part:
                    register_files.add(file_part)

            for reg_file in sorted(register_files):
                # Hard bound: only extend files that already have behavioral evidence
                if reg_file not in files_with_actions:
                    continue
                for sibling_nid in file_to_node_ids.get(reg_file, []):
                    s_name, _ = _node_id_to_name_and_file(sibling_nid)
                    if s_name and s_name not in node_names and s_name not in sibling_names:
                        sibling_names.add(s_name)
                if sibling_names:
                    sibling_files.append(reg_file)

            node_names = node_names | sibling_names

        # Collect actions in two passes to track provenance:
        # Pass 1: direct BFS-reachable names; Pass 2: sibling-extension names.
        matched_actions: list[dict[str, Any]] = []
        sibling_action_ids: set[str] = set()
        seen_action_ids: set[str] = set()

        def _collect_actions(names: set[str], is_sibling: bool) -> None:
            for name in names:
                expected_file = node_file_map.get(name)
                for scope, action_list in scope_actions.items():
                    if not (scope.endswith(":" + name) or scope == name):
                        continue
                    for action in action_list:
                        aid = action.get("action_id", "")
                        if aid in seen_action_ids:
                            continue
                        if expected_file:
                            action_file = action.get("file_path", "")
                            if action_file and not _files_match(action_file, expected_file):
                                continue
                        seen_action_ids.add(aid)
                        matched_actions.append(action)
                        if is_sibling:
                            sibling_action_ids.add(aid)

        _collect_actions(node_names - sibling_names, is_sibling=False)
        _collect_actions(sibling_names, is_sibling=True)

        action_ids = [a["action_id"] for a in matched_actions]
        evidence_refs = [ref for a in matched_actions for ref in a.get("evidence_refs", [])]
        dimensions = aggregate_dimensions(matched_actions)

        # Calibrated confidence: 2+ actions = MEDIUM, 1 action = LOW, 0 = LOW+inferred
        n = len(action_ids)
        if n >= 2:
            confidence = ConfidenceLevel.MEDIUM
            inferred = False
            gap_note = ""
        elif n == 1:
            confidence = ConfidenceLevel.LOW
            inferred = False
            gap_note = ""
        else:
            confidence = ConfidenceLevel.LOW
            inferred = True
            gap_note = "; no action records matched flow nodes — flow nodes may have no ability evidence"

        # Provenance note: distinguish direct-BFS steps from sibling-extension steps
        direct_count = len(action_ids) - len(sibling_action_ids)
        sibling_count = len(sibling_action_ids)
        if sibling_count > 0:
            sib_files_str = ", ".join(sibling_files[:5])
            gap_note += (
                f"; {direct_count} step(s) from BFS-reachable nodes, "
                f"{sibling_count} step(s) via file-sibling extension "
                f"(register-pattern files: {sib_files_str})"
            )

        workflow_id = _generate_id("workflow", flow_id)
        entry_func = root_node_id.split(":")[-1] if root_node_id else ""
        dim_str = ", ".join(d.value if hasattr(d, "value") else str(d) for d in dimensions[:3])
        func_part = f":{entry_func}" if entry_func else ""
        label = f"workflow from {entry_point}{func_part}" + (f" [{dim_str}]" if dim_str else "")

        records.append(WorkflowRecord(
            workflow_id=workflow_id,
            label=label,
            step_action_ids=action_ids,
            entry_point=entry_point,
            dimensions=dimensions,
            evidence_refs=evidence_refs[:20],
            confidence=confidence,
            inferred=inferred,
            derivation=_make_derivation(
                DerivationBasis.FLOW_MEMBERSHIP,
                source_layer=LayerID.ACTION,
                source_ids=action_ids,
                notes=f"flow: {flow_id}" + gap_note,
            ),
        ))

    return records


def workflow_records_json_path(output_dir: Path) -> Path:
    return output_dir / "meaning" / "workflow_records.json"


def _derive_workflows_capability(context: CapabilityContext) -> dict[str, Any]:
    path = workflow_records_json_path(context.runtime.output_dir)

    if context.cache_ready(path, output_name="workflow_records"):
        ref = context.load_cached_json_artifact(KIND, path, views={}, metadata={"cached": True})
        data = context.read(ref)
        return {
            "workflow_records": ref,
            "workflow_records_path": str(path),
            "workflow_count": len(data) if isinstance(data, list) else 0,
            "cached": True,
        }

    actions = context.read_input("action_records")
    flow_map = context.read_input("flow_map")
    enriched = context.read_input("enriched_file_breakdowns")

    if not isinstance(actions, list):
        actions = list(actions) if actions else []
    if not isinstance(flow_map, dict):
        flow_map = {}
    if not isinstance(enriched, dict):
        enriched = {}

    records = _derive_workflows(actions, flow_map, enriched)
    data = [to_dict(r) for r in records]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ref = context.record_artifact(KIND, data, path=path)
    return {
        "workflow_records": ref,
        "workflow_records_path": str(path),
        "workflow_count": len(data),
        "cached": False,
    }


def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="meaning.workflows.derive",
        pack_id=PACK_ID,
        version="1",
        display_name="Derive Workflow Records",
        description="Derive WorkflowRecords by mapping ActionRecords onto flow_map BFS traversals.",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("action_records", "flow_map", "enriched_file_breakdowns"),
            output=("workflow_records", "workflow_records_path", "workflow_count", "cached"),
        ),
        implementation_logic=_derive_workflows_capability,
        tags=("meaning", "workflow"),
    ))
