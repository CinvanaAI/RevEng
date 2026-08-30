"""SubsystemSummaryAgent — derives SubsystemSummaryRecords from ModuleSummaryRecords.

PROVISIONAL in Phase 1: subsystem identity is derived from top-level path prefix
grouping (structural approximation), not from resolved semantic boundaries.
All produced records carry phase1_approximation=True.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reveng.analysis_engine.agentic.tasks.functions import _make_derivation
from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.analysis_engine.meaning.aggregation import aggregate_confidence, aggregate_dimensions
from reveng.analysis_engine.meaning.compression import compress_evidence_refs, compress_label
from reveng.analysis_engine.meaning.confidence import ConfidenceLevel
from reveng.analysis_engine.meaning.derivation import DerivationBasis
from reveng.analysis_engine.meaning.layers import LayerID
from reveng.analysis_engine.meaning.records import SubsystemSummaryRecord, to_dict

PACK_ID = "reveng.pack.meaning_layer"
KIND = "meaning.subsystem_summary_records.v1"


def _top_level_prefix(module_path: str) -> str:
    """Extract the first path component as the subsystem prefix."""
    if not module_path:
        return "<root>"
    parts = module_path.replace("\\", "/").split("/")
    return parts[0] if parts else "<root>"


def _derive_subsystem_summaries(
    module_summaries: list[dict[str, Any]],
    cluster_map: dict[str, Any],
) -> list[SubsystemSummaryRecord]:
    records: list[SubsystemSummaryRecord] = []

    # Group module summaries by top-level path prefix
    prefix_modules: dict[str, list[dict[str, Any]]] = {}
    for module in module_summaries:
        module_path = module.get("module_path", "")
        prefix = _top_level_prefix(module_path)
        prefix_modules.setdefault(prefix, []).append(module)

    for prefix, modules in prefix_modules.items():
        module_ids = [m["module_path"] for m in modules if "module_path" in m]
        dimensions = aggregate_dimensions(modules)

        if modules:
            confidence = aggregate_confidence(modules)
        else:
            confidence = ConfidenceLevel.LOW

        if dimensions:
            dim_names = [d.value if hasattr(d, "value") else str(d) for d in dimensions[:3]]
            label = f"{prefix}: {', '.join(dim_names)} [{len(modules)} module(s)]"
        elif modules:
            label = f"{prefix}: {len(modules)} module(s)"
        else:
            label = f"subsystem: {prefix}"

        evidence_refs = compress_evidence_refs(
            list(dict.fromkeys(ref for m in modules for ref in m.get("evidence_refs", [])))
        )

        records.append(SubsystemSummaryRecord(
            subsystem_id=prefix,
            label=label,
            module_summary_ids=module_ids,
            dimensions=dimensions,
            evidence_refs=evidence_refs,
            confidence=confidence,
            inferred=False,
            phase1_approximation=True,
            derivation=_make_derivation(
                DerivationBasis.GROUPING,
                source_layer=LayerID.MODULE_SUMMARY,
                source_ids=module_ids,
                notes="path-prefix heuristic, Phase 1 approximation",
                phase1_approximation=True,
            ),
        ))

    return records


def subsystem_summary_records_json_path(output_dir: Path) -> Path:
    return output_dir / "meaning" / "subsystem_summary_records.json"


def _derive_subsystem_summaries_capability(context: CapabilityContext) -> dict[str, Any]:
    path = subsystem_summary_records_json_path(context.runtime.output_dir)

    if context.cache_ready(path, output_name="subsystem_summary_records"):
        ref = context.load_cached_json_artifact(KIND, path, views={}, metadata={"cached": True})
        data = context.read(ref)
        return {
            "subsystem_summary_records": ref,
            "subsystem_summary_records_path": str(path),
            "subsystem_summary_count": len(data) if isinstance(data, list) else 0,
            "cached": True,
        }

    module_summaries = context.read_input("module_summary_records")
    cluster_map = context.read_input("cluster_map")

    if not isinstance(module_summaries, list):
        module_summaries = list(module_summaries) if module_summaries else []
    if not isinstance(cluster_map, dict):
        cluster_map = {}

    records = _derive_subsystem_summaries(module_summaries, cluster_map)
    data = [to_dict(r) for r in records]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ref = context.record_artifact(KIND, data, path=path)
    return {
        "subsystem_summary_records": ref,
        "subsystem_summary_records_path": str(path),
        "subsystem_summary_count": len(data),
        "cached": False,
    }


def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="meaning.subsystems.summarize",
        pack_id=PACK_ID,
        version="1",
        display_name="Derive Subsystem Summary Records",
        description=(
            "Derive SubsystemSummaryRecords from module summaries. "
            "PROVISIONAL: Phase 1 structural approximation via path-prefix grouping."
        ),
        capability_type="function",
        contract=CapabilityContract(
            inputs=("module_summary_records", "cluster_map"),
            output=("subsystem_summary_records", "subsystem_summary_records_path", "subsystem_summary_count", "cached"),
        ),
        implementation_logic=_derive_subsystem_summaries_capability,
        tags=("meaning", "subsystem"),
    ))
