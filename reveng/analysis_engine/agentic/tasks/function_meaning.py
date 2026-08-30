"""FunctionMeaningAgent — derives FunctionMeaningRecords from ActionRecords.

For each distinct (file_path, function_scope) pair across all ActionRecords,
builds one FunctionMeaningRecord aggregating its actions. Also produces
structurally-discovered records for functions that have no action records.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reveng.analysis_engine.agentic.tasks.functions import (
    _body_has_nontrivial_content,
    _build_file_index,
    _count_distinct_callees,
    _generate_id,
    _get_callee_names,
    _make_derivation,
    _scope_display,
)
from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.analysis_engine.meaning.aggregation import aggregate_confidence, aggregate_dimensions
from reveng.analysis_engine.meaning.compression import compress_evidence_refs
from reveng.analysis_engine.meaning.confidence import ConfidenceLevel
from reveng.analysis_engine.meaning.derivation import DerivationBasis
from reveng.analysis_engine.meaning.dimensions import DimensionID
from reveng.analysis_engine.meaning.layers import LayerID
from reveng.analysis_engine.meaning.records import (
    FunctionMeaningRecord,
    RESOLUTION_BEHAVIORALLY_RESOLVED,
    RESOLUTION_STRUCTURALLY_DISCOVERED,
    BEHAVIOR_CLASS_BEHAVIORALLY_RESOLVED,
    BEHAVIOR_CLASS_COORDINATOR,
    BEHAVIOR_CLASS_THIN_WRAPPER,
    BEHAVIOR_CLASS_PURE_WRAPPER,
    BEHAVIOR_CLASS_STRUCTURALLY_DISCOVERED,
    to_dict,
)

PACK_ID = "reveng.pack.meaning_layer"
KIND = "meaning.function_meaning_records.v1"


def _derive_function_meanings(
    actions: list[dict[str, Any]],
    enriched: dict[str, Any],
) -> list[FunctionMeaningRecord]:
    file_index = _build_file_index(enriched)
    records: list[FunctionMeaningRecord] = []

    # Group action records by (file_path, function_scope)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for action in actions:
        key = (action.get("file_path", ""), action.get("function_scope", ""))
        groups.setdefault(key, []).append(action)

    seen_functions: set[tuple[str, str]] = set()

    # Build behaviorally-resolved records from action groups
    for (file_path, scope), action_list in groups.items():
        if not file_path or not scope:
            continue
        seen_functions.add((file_path, scope))

        action_ids = [a["action_id"] for a in action_list]
        ability_ids = list({a["ability_id"] for a in action_list})
        dimensions = aggregate_dimensions(action_list)
        confidence = aggregate_confidence(action_list)
        function_id = _generate_id("function", file_path, scope)

        # Look up lineno/end_lineno from enriched defined_symbols
        lineno = 0
        end_lineno = 0
        file_record = file_index.get(file_path)
        if file_record:
            for sym in file_record.get("defined_symbols", []):
                name = sym.get("name", "")
                if name == scope or scope.endswith("." + name) or scope.endswith(":" + name):
                    lineno = sym.get("lineno", 0)
                    end_lineno = sym.get("end_lineno", lineno)
                    break

        evidence_refs = compress_evidence_refs(
            [ref for a in action_list for ref in a.get("evidence_refs", [])]
        )

        # Classify behavior: coordinator if few own actions but many callees
        callee_count = _count_distinct_callees(file_index, file_path, scope)
        if len(action_ids) <= 2 and callee_count >= 3:
            behavior_class = BEHAVIOR_CLASS_COORDINATOR
        else:
            behavior_class = BEHAVIOR_CLASS_BEHAVIORALLY_RESOLVED

        display = _scope_display(scope)
        dim_names = [d.value if hasattr(d, "value") else str(d) for d in dimensions[:2]]
        if behavior_class == BEHAVIOR_CLASS_COORDINATOR:
            label = f"{display}: coordinates {callee_count} callees" + (
                f" [{', '.join(dim_names)}]" if dim_names else ""
            )
        else:
            label = f"{display}: {', '.join(dim_names)}" if dim_names else f"{display}: [resolved]"

        records.append(FunctionMeaningRecord(
            function_id=function_id,
            label=label,
            file_path=file_path,
            function_scope=scope,
            lineno=lineno,
            end_lineno=end_lineno,
            action_ids=action_ids,
            ability_ids=ability_ids,
            dimensions=dimensions,
            evidence_refs=evidence_refs,
            confidence=confidence,
            inferred=False,
            resolution_status=RESOLUTION_BEHAVIORALLY_RESOLVED,
            behavior_class=behavior_class,
            derivation=_make_derivation(
                DerivationBasis.AGGREGATION,
                source_layer=LayerID.ACTION,
                source_ids=action_ids,
                notes=f"aggregated {len(action_ids)} actions for {scope} in {file_path}"
                      + (f"; coordinator ({callee_count} callees)" if behavior_class == BEHAVIOR_CLASS_COORDINATOR else ""),
            ),
        ))

    # Build structurally-discovered records for functions not in any action group
    for file_path, file_record in file_index.items():
        if "parse_error" in file_record:
            continue
        for sym in file_record.get("defined_symbols", []):
            sym_type = sym.get("symbol_type", "")
            if sym_type not in ("function", "method", "async_function"):
                continue
            name = sym.get("name", "")
            if not name:
                continue
            # Build a qualified scope from the symbol's enclosing scope context.
            # Methods carry "scope": "module > class:ClassName"; functions carry "scope": "module".
            sym_scope_prefix = sym.get("scope", "module")
            if sym_type == "method":
                qualified_scope = f"{sym_scope_prefix} > method:{name}"
            else:
                qualified_scope = f"{sym_scope_prefix} > function:{name}"

            # Check if this function was already covered by a behaviorally-resolved record
            if (file_path, qualified_scope) in seen_functions:
                continue
            already_seen = any(
                fp == file_path and (
                    sc == name or sc == qualified_scope
                    or sc.endswith("." + name) or sc.endswith(":" + name)
                )
                for fp, sc in seen_functions
            )
            if already_seen:
                continue

            function_id = _generate_id("function", file_path, qualified_scope)
            lineno = sym.get("lineno", 0)
            end_lineno = sym.get("end_lineno", lineno)

            callee_count = _count_distinct_callees(file_index, file_path, qualified_scope)
            file_record_for_scope = file_index.get(file_path, {})
            if callee_count >= 2:
                behavior_class = BEHAVIOR_CLASS_COORDINATOR
            elif callee_count == 1 and _body_has_nontrivial_content(file_record_for_scope, qualified_scope):
                behavior_class = BEHAVIOR_CLASS_THIN_WRAPPER
            elif callee_count >= 1:
                behavior_class = BEHAVIOR_CLASS_PURE_WRAPPER
            else:
                behavior_class = BEHAVIOR_CLASS_STRUCTURALLY_DISCOVERED

            display = _scope_display(qualified_scope)
            if behavior_class == BEHAVIOR_CLASS_COORDINATOR:
                label = f"{display}: coordinates {callee_count} callees [no own actions]"
                notes = f"no own actions; orchestrates {callee_count} callees — structurally discovered"
            elif behavior_class == BEHAVIOR_CLASS_THIN_WRAPPER:
                label = f"{display}: thin wrapper [delegates with non-trivial body]"
                notes = "no own actions; 1 callee with non-trivial body (assignments/raises/control_flow) — thin_wrapper"
            elif behavior_class == BEHAVIOR_CLASS_PURE_WRAPPER:
                label = f"{display}: delegates to {callee_count} callee(s) [no own actions]"
                notes = f"no own actions; trivial pass-through to {callee_count} callee(s) — pure_wrapper"
            else:
                label = f"{display}: [discovered; no actions or callees]"
                notes = "no matching action records; function known from defined_symbols only"

            records.append(FunctionMeaningRecord(
                function_id=function_id,
                label=label,
                file_path=file_path,
                function_scope=qualified_scope,
                lineno=lineno,
                end_lineno=end_lineno,
                action_ids=[],
                ability_ids=[],
                dimensions=[],
                evidence_refs=[],
                confidence=ConfidenceLevel.UNKNOWN,
                inferred=True,
                resolution_status=RESOLUTION_STRUCTURALLY_DISCOVERED,
                behavior_class=behavior_class,
                derivation=_make_derivation(
                    DerivationBasis.AGGREGATION,
                    source_layer=LayerID.ACTION,
                    source_ids=[],
                    notes=notes,
                ),
            ))

    # -----------------------------------------------------------------------
    # Phase 11: Behavioral dimension propagation for coordinators/thin_wrappers
    # -----------------------------------------------------------------------
    # Build a scope-name → dimensions map from the action-bearing pass records.
    # Key is the bare function name (last component) for fuzzy matching.
    scope_dims: dict[str, list] = {}
    for rec in records:
        if rec.dimensions and rec.behavior_class in (
            BEHAVIOR_CLASS_BEHAVIORALLY_RESOLVED, BEHAVIOR_CLASS_COORDINATOR
        ):
            name = rec.function_scope.split(":")[-1] if ":" in rec.function_scope else rec.function_scope
            if name and name not in scope_dims:
                scope_dims[name] = rec.dimensions

    # Second pass: propagate one-hop callee dimensions to structural coordinators
    # and thin_wrappers that have no own dimensions.
    for rec in records:
        if rec.dimensions:
            continue  # already has dimensions — do not overwrite
        if rec.behavior_class not in (BEHAVIOR_CLASS_COORDINATOR, BEHAVIOR_CLASS_THIN_WRAPPER):
            continue

        callee_names = _get_callee_names(file_index, rec.file_path, rec.function_scope)
        inferred_dims: list = []
        seen: set = set()
        for name in callee_names:
            for dim in scope_dims.get(name, []):
                key = dim.value if hasattr(dim, "value") else str(dim)
                if key not in seen:
                    seen.add(key)
                    inferred_dims.append(dim)

        if not inferred_dims:
            continue

        rec.dimensions = inferred_dims
        rec.inferred = True
        rec.confidence = ConfidenceLevel.LOW
        callee_count = len(callee_names)
        dim_names = [d.value if hasattr(d, "value") else str(d) for d in inferred_dims[:2]]
        rec.label = (
            f"{_scope_display(rec.function_scope)}: coordinates {callee_count} callees"
            f" [{', '.join(dim_names)}]"
            if rec.behavior_class == BEHAVIOR_CLASS_COORDINATOR
            else f"{_scope_display(rec.function_scope)}: thin wrapper [{', '.join(dim_names)}]"
        )
        # Append propagation note to derivation
        if rec.derivation and rec.derivation.notes:
            rec.derivation = _make_derivation(
                DerivationBasis.AGGREGATION,
                source_layer=LayerID.ACTION,
                source_ids=[],
                notes=rec.derivation.notes + f"; dimensions inferred from {len(callee_names)} callee(s) [AGGREGATION, one-hop]",
            )

    return records


def function_meaning_records_json_path(output_dir: Path) -> Path:
    return output_dir / "meaning" / "function_meaning_records.json"


def _derive_function_meanings_capability(context: CapabilityContext) -> dict[str, Any]:
    path = function_meaning_records_json_path(context.runtime.output_dir)

    if context.cache_ready(path, output_name="function_meaning_records"):
        ref = context.load_cached_json_artifact(KIND, path, views={}, metadata={"cached": True})
        data = context.read(ref)
        return {
            "function_meaning_records": ref,
            "function_meaning_records_path": str(path),
            "function_meaning_count": len(data) if isinstance(data, list) else 0,
            "cached": True,
        }

    actions = context.read_input("action_records")
    enriched = context.read_input("enriched_file_breakdowns")

    if not isinstance(actions, list):
        actions = list(actions) if actions else []

    records = _derive_function_meanings(actions, enriched)
    data = [to_dict(r) for r in records]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ref = context.record_artifact(KIND, data, path=path)
    return {
        "function_meaning_records": ref,
        "function_meaning_records_path": str(path),
        "function_meaning_count": len(data),
        "cached": False,
    }


def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="meaning.functions.derive",
        pack_id=PACK_ID,
        version="1",
        display_name="Derive Function Meaning Records",
        description="Derive FunctionMeaningRecords by aggregating ActionRecords per function scope.",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("action_records", "enriched_file_breakdowns", "relation_map"),
            output=("function_meaning_records", "function_meaning_records_path", "function_meaning_count", "cached"),
        ),
        implementation_logic=_derive_function_meanings_capability,
        tags=("meaning", "function"),
    ))
