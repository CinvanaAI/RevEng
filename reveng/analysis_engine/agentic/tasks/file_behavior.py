"""FileBehaviorAgent — derives FileBehaviorRecords from FunctionMeaningRecords.

What a file DOES — derived from realized actions and function meanings.
Depends on ActionRecord and FunctionMeaningRecord; available later.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reveng.analysis_engine.agentic.tasks.functions import _build_file_index, _is_test_file, _make_derivation
from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.analysis_engine.meaning.aggregation import (
    aggregate_ability_ids,
    aggregate_action_ids,
    aggregate_confidence,
    aggregate_dimensions,
    aggregate_function_ids,
)
from reveng.analysis_engine.meaning.compression import compress_evidence_refs
from reveng.analysis_engine.meaning.confidence import ConfidenceLevel, _CONFIDENCE_RANK
from reveng.analysis_engine.meaning.derivation import DerivationBasis
from reveng.analysis_engine.meaning.layers import LayerID
from reveng.analysis_engine.meaning.records import (
    FileBehaviorRecord,
    RESOLUTION_STRUCTURALLY_DISCOVERED,
    to_dict,
)

PACK_ID = "reveng.pack.meaning_layer"
KIND = "meaning.file_behavior_records.v1"

_ACTIVE_BEHAVIOR_CLASSES = frozenset(("behaviorally_resolved", "coordinator", "thin_wrapper"))


def _density_confidence_floor(current: ConfidenceLevel, density: float) -> ConfidenceLevel:
    """Phase 12 density floor: raise confidence based on fraction of active behavior classes."""
    rank = _CONFIDENCE_RANK[current]
    if density >= 0.50 and rank < _CONFIDENCE_RANK[ConfidenceLevel.MEDIUM]:
        return ConfidenceLevel.MEDIUM
    if density >= 0.25 and rank < _CONFIDENCE_RANK[ConfidenceLevel.LOW]:
        return ConfidenceLevel.LOW
    return current


def _derive_file_behaviors(
    function_meanings: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    enriched: dict[str, Any],
) -> list[FileBehaviorRecord]:
    file_index = _build_file_index(enriched)
    records: list[FileBehaviorRecord] = []

    # Group function meanings by file_path
    file_functions: dict[str, list[dict[str, Any]]] = {fp: [] for fp in file_index}
    for fm in function_meanings:
        fp = fm.get("file_path", "")
        if fp in file_functions:
            file_functions[fp].append(fm)

    for file_path, file_record in file_index.items():
        if "parse_error" in file_record:
            continue

        matched_functions = file_functions.get(file_path, [])

        # Only use behaviorally-resolved functions for action/ability aggregation
        resolved = [
            fm for fm in matched_functions
            if fm.get("resolution_status") != RESOLUTION_STRUCTURALLY_DISCOVERED
        ]

        function_ids = aggregate_function_ids(matched_functions)
        action_ids = aggregate_action_ids(resolved)
        ability_ids = aggregate_ability_ids(resolved)
        dimensions = aggregate_dimensions(resolved)

        # Confidence: if only structurally-discovered functions, inherit UNKNOWN
        if resolved:
            confidence = aggregate_confidence(resolved)
            inferred = False
            gap_note = ""
        elif matched_functions:
            confidence = ConfidenceLevel.UNKNOWN
            inferred = True
            gap_note = (
                f"; all {len(matched_functions)} function(s) structurally discovered — "
                "no behavioral evidence available"
            )
        else:
            confidence = ConfidenceLevel.LOW
            inferred = True
            gap_note = "; no function meanings found for file — behavioral meaning fully absent"

        # Phase 12: density-weighted confidence floor — same rule as file_purpose
        if matched_functions:
            active = sum(
                1 for fm in matched_functions
                if fm.get("behavior_class", "") in _ACTIVE_BEHAVIOR_CLASSES
            )
            density = active / len(matched_functions)
            floored = _density_confidence_floor(confidence, density)
            if floored != confidence:
                confidence = floored
                gap_note += (
                    f"; confidence raised to {confidence.value} by behavioral density "
                    f"({density:.0%} active functions)"
                )

        # Build behavioral label from resolved function labels
        func_labels = [fm.get("label", "") for fm in resolved[:3] if fm.get("label")]
        if func_labels:
            label = "; ".join(func_labels)
        else:
            label = f"file {file_path} [no resolved behaviors]"

        evidence_refs = compress_evidence_refs(
            [ref for fm in resolved for ref in fm.get("evidence_refs", [])]
        )

        records.append(FileBehaviorRecord(
            file_path=file_path,
            label=label,
            function_meaning_ids=function_ids,
            action_ids=action_ids,
            ability_ids=ability_ids,
            dimensions=dimensions,
            evidence_refs=evidence_refs,
            confidence=confidence,
            inferred=inferred,
            is_test=_is_test_file(file_path),
            derivation=_make_derivation(
                DerivationBasis.AGGREGATION,
                source_layer=LayerID.FUNCTION_MEANING,
                source_ids=function_ids,
                notes=f"aggregated {len(matched_functions)} function meanings for {file_path}" + gap_note,
            ),
        ))

    return records


def file_behavior_records_json_path(output_dir: Path) -> Path:
    return output_dir / "meaning" / "file_behavior_records.json"


def _derive_file_behaviors_capability(context: CapabilityContext) -> dict[str, Any]:
    path = file_behavior_records_json_path(context.runtime.output_dir)

    if context.cache_ready(path, output_name="file_behavior_records"):
        ref = context.load_cached_json_artifact(KIND, path, views={}, metadata={"cached": True})
        data = context.read(ref)
        return {
            "file_behavior_records": ref,
            "file_behavior_records_path": str(path),
            "file_behavior_count": len(data) if isinstance(data, list) else 0,
            "cached": True,
        }

    function_meanings = context.read_input("function_meaning_records")
    actions = context.read_input("action_records")
    enriched = context.read_input("enriched_file_breakdowns")

    if not isinstance(function_meanings, list):
        function_meanings = list(function_meanings) if function_meanings else []
    if not isinstance(actions, list):
        actions = list(actions) if actions else []

    records = _derive_file_behaviors(function_meanings, actions, enriched)
    data = [to_dict(r) for r in records]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ref = context.record_artifact(KIND, data, path=path)
    return {
        "file_behavior_records": ref,
        "file_behavior_records_path": str(path),
        "file_behavior_count": len(data),
        "cached": False,
    }


def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="meaning.files.behavior",
        pack_id=PACK_ID,
        version="1",
        display_name="Derive File Behavior Records",
        description="Derive FileBehaviorRecords from function meanings and actions (action-based, late).",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("function_meaning_records", "action_records", "enriched_file_breakdowns"),
            output=("file_behavior_records", "file_behavior_records_path", "file_behavior_count", "cached"),
        ),
        implementation_logic=_derive_file_behaviors_capability,
        tags=("meaning", "file", "behavior"),
    ))
