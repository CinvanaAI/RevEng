"""ModuleSummaryAgent — derives ModuleSummaryRecords from cluster_map.

PROVISIONAL in Phase 1: module identity is derived from cluster grouping
heuristics (structural approximation), not from resolved semantic boundaries.
All produced records carry phase1_approximation=True.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from collections import Counter

from reveng.analysis_engine.agentic.tasks.functions import _make_derivation
from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.analysis_engine.meaning.aggregation import aggregate_confidence, aggregate_dimensions
from reveng.analysis_engine.meaning.compression import compress_evidence_refs, compress_label
from reveng.analysis_engine.meaning.confidence import ConfidenceLevel, _CONFIDENCE_RANK
from reveng.analysis_engine.meaning.derivation import DerivationBasis
from reveng.analysis_engine.meaning.layers import LayerID
from reveng.analysis_engine.meaning.records import ModuleSummaryRecord, to_dict

PACK_ID = "reveng.pack.meaning_layer"
KIND = "meaning.module_summary_records.v1"


def _derive_module_summaries(
    file_purposes: list[dict[str, Any]],
    file_behaviors: list[dict[str, Any]],
    cluster_map: dict[str, Any],
) -> list[ModuleSummaryRecord]:
    records: list[ModuleSummaryRecord] = []

    # Build lookup: file_path -> purpose/behavior dict
    purpose_index = {fp["file_path"]: fp for fp in file_purposes if "file_path" in fp}
    behavior_index = {fb["file_path"]: fb for fb in file_behaviors if "file_path" in fb}

    clusters = cluster_map.get("clusters", []) if isinstance(cluster_map, dict) else []

    for cluster in clusters:
        cluster_id = cluster.get("cluster_id", "")
        cluster_files = cluster.get("observed", {}).get("files", [])
        cluster_type = cluster.get("derived", {}).get("cluster_type", "unknown")

        matched_purposes = [purpose_index[fp] for fp in cluster_files if fp in purpose_index]
        matched_behaviors = [behavior_index[fp] for fp in cluster_files if fp in behavior_index]

        purpose_ids = [p["file_path"] for p in matched_purposes]
        behavior_ids = [b["file_path"] for b in matched_behaviors]

        all_records = matched_purposes + matched_behaviors
        dimensions = aggregate_dimensions(all_records)

        if all_records:
            confidence = aggregate_confidence(all_records)
        else:
            confidence = ConfidenceLevel.LOW

        # Phase 8: structural confidence floor — additive only, never lowers.
        # Applies when vocabulary thinness forces aggregate_confidence to UNKNOWN.
        # Uses cluster structural signals (call-edge density + file count) as
        # evidence that the module has real behavioral weight, independent of
        # whether individual records have recognized ability patterns.
        if confidence == ConfidenceLevel.UNKNOWN:
            file_count = cluster.get("observed", {}).get("file_count", len(cluster_files))
            internal_calls = cluster.get("observed", {}).get("internal_call_edge_count", 0)
            outbound = cluster.get("derived", {}).get("outbound_cross_cluster_edge_count", 0)
            inbound = cluster.get("derived", {}).get("inbound_cross_cluster_edge_count", 0)
            total_calls = internal_calls + outbound + inbound
            top_dimension = dimensions[0] if dimensions else None
            if file_count >= 5 and total_calls >= 10:
                confidence = ConfidenceLevel.LOW
            elif file_count >= 2 and total_calls >= 5 and top_dimension:
                confidence = ConfidenceLevel.LOW

        # Phase 12 extension: density floor at module layer — same rule as file layers.
        # If ≥50% of contained files have MEDIUM+ confidence → module ≥ MEDIUM.
        # If ≥25% → module ≥ LOW. Uses file_purpose records as the density signal
        # (one record per file, so it's a clean per-file fraction).
        if matched_purposes:
            _MEDIUM_PLUS = {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM}
            medium_plus_count = sum(
                1 for p in matched_purposes
                if ConfidenceLevel(p.get("confidence", "unknown")) in _MEDIUM_PLUS
            )
            density = medium_plus_count / len(matched_purposes)
            rank = _CONFIDENCE_RANK[confidence]
            if density >= 0.50 and rank < _CONFIDENCE_RANK[ConfidenceLevel.MEDIUM]:
                confidence = ConfidenceLevel.MEDIUM
            elif density >= 0.25 and rank < _CONFIDENCE_RANK[ConfidenceLevel.LOW]:
                confidence = ConfidenceLevel.LOW

        # Label from dimensions + file count (more scannable than echoing child labels)
        if dimensions:
            dim_names = [d.value if hasattr(d, "value") else str(d) for d in dimensions[:3]]
            label = f"{cluster_id}: {', '.join(dim_names)} [{len(cluster_files)} file(s)]"
        elif cluster_files:
            label = f"{cluster_id}: {len(cluster_files)} file(s)"
        else:
            label = f"module: {cluster_id}"

        evidence_refs = compress_evidence_refs(
            list(dict.fromkeys(ref for r in all_records for ref in r.get("evidence_refs", [])))
        )

        # Semantic profile: per-dimension ability counts + structural role augmentation
        dim_counter: Counter[str] = Counter()
        for r in all_records:
            for dim in r.get("dimensions", []):
                dim_v = dim.value if hasattr(dim, "value") else str(dim)
                dim_counter[dim_v] += 1
        ability_ids_in_module: list[str] = list(dict.fromkeys(
            aid
            for r in matched_purposes + matched_behaviors
            for aid in r.get("ability_ids", [])
        ))
        structural_role = cluster.get("derived", {}).get("structural_role", "unknown")
        semantic_profile: dict = {
            "structural_role": structural_role,
            "dimension_counts": dict(dim_counter.most_common()),
            "ability_count": len(ability_ids_in_module),
            "file_count": len(cluster_files),
            "has_test_files": any("test" in fp.lower() for fp in cluster_files),
        }

        records.append(ModuleSummaryRecord(
            module_path=cluster_id,
            label=label,
            file_purpose_ids=purpose_ids,
            file_behavior_ids=behavior_ids,
            dimensions=dimensions,
            evidence_refs=evidence_refs,
            confidence=confidence,
            inferred=False,
            phase1_approximation=True,
            derivation=_make_derivation(
                DerivationBasis.GROUPING,
                source_layer=LayerID.FILE_PURPOSE,
                source_ids=purpose_ids + behavior_ids,
                notes=f"cluster heuristic: type={cluster_type}; role={structural_role}",
                phase1_approximation=True,
            ),
            semantic_profile=semantic_profile,
        ))

    return records


def module_summary_records_json_path(output_dir: Path) -> Path:
    return output_dir / "meaning" / "module_summary_records.json"


def _derive_module_summaries_capability(context: CapabilityContext) -> dict[str, Any]:
    path = module_summary_records_json_path(context.runtime.output_dir)

    if context.cache_ready(path, output_name="module_summary_records"):
        ref = context.load_cached_json_artifact(KIND, path, views={}, metadata={"cached": True})
        data = context.read(ref)
        return {
            "module_summary_records": ref,
            "module_summary_records_path": str(path),
            "module_summary_count": len(data) if isinstance(data, list) else 0,
            "cached": True,
        }

    file_purposes = context.read_input("file_purpose_records")
    file_behaviors = context.read_input("file_behavior_records")
    cluster_map = context.read_input("cluster_map")

    if not isinstance(file_purposes, list):
        file_purposes = list(file_purposes) if file_purposes else []
    if not isinstance(file_behaviors, list):
        file_behaviors = list(file_behaviors) if file_behaviors else []
    if not isinstance(cluster_map, dict):
        cluster_map = {}

    records = _derive_module_summaries(file_purposes, file_behaviors, cluster_map)
    data = [to_dict(r) for r in records]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ref = context.record_artifact(KIND, data, path=path)
    return {
        "module_summary_records": ref,
        "module_summary_records_path": str(path),
        "module_summary_count": len(data),
        "cached": False,
    }


def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="meaning.modules.summarize",
        pack_id=PACK_ID,
        version="1",
        display_name="Derive Module Summary Records",
        description=(
            "Derive ModuleSummaryRecords from cluster_map. "
            "PROVISIONAL: Phase 1 structural approximation via cluster heuristics."
        ),
        capability_type="function",
        contract=CapabilityContract(
            inputs=("file_purpose_records", "file_behavior_records", "cluster_map"),
            output=("module_summary_records", "module_summary_records_path", "module_summary_count", "cached"),
        ),
        implementation_logic=_derive_module_summaries_capability,
        tags=("meaning", "module"),
    ))
