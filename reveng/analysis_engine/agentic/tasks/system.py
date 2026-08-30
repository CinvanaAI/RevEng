"""SystemSummaryAgent — derives SystemSummaryRecord from SubsystemSummaryRecords.

Aggregates the top-level system summary. If only one subsystem exists and
it fully covers all content, uses PASS_THROUGH_COMPRESSION instead of AGGREGATION.
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
from reveng.analysis_engine.meaning.compression import compress_evidence_refs, compress_label, is_pass_through
from reveng.analysis_engine.meaning.derivation import DerivationBasis
from reveng.analysis_engine.meaning.layers import LayerID
from reveng.analysis_engine.meaning.records import SystemSummaryRecord, to_dict

PACK_ID = "reveng.pack.meaning_layer"
KIND = "meaning.system_summary_record.v1"


def _derive_system_summary(
    subsystem_summaries: list[dict[str, Any]],
) -> SystemSummaryRecord:
    subsystem_ids = [s["subsystem_id"] for s in subsystem_summaries if "subsystem_id" in s]
    dimensions = aggregate_dimensions(subsystem_summaries)
    confidence = aggregate_confidence(subsystem_summaries) if subsystem_summaries else None

    from reveng.analysis_engine.meaning.confidence import ConfidenceLevel
    if confidence is None:
        confidence = ConfidenceLevel.LOW

    pass_through = is_pass_through(subsystem_summaries)

    # Label from top dimensions across all subsystems + subsystem count
    if dimensions:
        from collections import Counter
        dim_strs = [d.value if hasattr(d, "value") else str(d) for d in dimensions]
        top_dims = [d for d, _ in Counter(dim_strs).most_common(3)]
        label = f"system: {', '.join(top_dims)} [{len(subsystem_summaries)} subsystem(s)]"
    elif subsystem_summaries:
        label = f"system: {len(subsystem_summaries)} subsystem(s)"
    else:
        label = "system summary"

    evidence_refs = compress_evidence_refs(
        list(dict.fromkeys(ref for s in subsystem_summaries for ref in s.get("evidence_refs", [])))
    )

    basis = DerivationBasis.PASS_THROUGH_COMPRESSION if pass_through else DerivationBasis.AGGREGATION

    return SystemSummaryRecord(
        label=label,
        subsystem_summary_ids=subsystem_ids,
        dimensions=dimensions,
        evidence_refs=evidence_refs,
        confidence=confidence,
        inferred=False,
        is_pass_through=pass_through,
        derivation=_make_derivation(
            basis,
            source_layer=LayerID.SUBSYSTEM_SUMMARY,
            source_ids=subsystem_ids,
            notes=f"aggregated {len(subsystem_summaries)} subsystem summaries",
        ),
    )


def system_summary_json_path(output_dir: Path) -> Path:
    return output_dir / "meaning" / "system_summary_record.json"


def _derive_system_summary_capability(context: CapabilityContext) -> dict[str, Any]:
    path = system_summary_json_path(context.runtime.output_dir)

    if context.cache_ready(path, output_name="system_summary_record"):
        ref = context.load_cached_json_artifact(KIND, path, views={}, metadata={"cached": True})
        return {
            "system_summary_record": ref,
            "system_summary_path": str(path),
            "cached": True,
        }

    subsystem_summaries = context.read_input("subsystem_summary_records")

    if not isinstance(subsystem_summaries, list):
        subsystem_summaries = list(subsystem_summaries) if subsystem_summaries else []

    record = _derive_system_summary(subsystem_summaries)
    data = to_dict(record)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ref = context.record_artifact(KIND, data, path=path)
    return {
        "system_summary_record": ref,
        "system_summary_path": str(path),
        "cached": False,
    }


def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="meaning.system.summarize",
        pack_id=PACK_ID,
        version="1",
        display_name="Derive System Summary Record",
        description="Derive SystemSummaryRecord by aggregating SubsystemSummaryRecords.",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("subsystem_summary_records",),
            output=("system_summary_record", "system_summary_path", "cached"),
        ),
        implementation_logic=_derive_system_summary_capability,
        tags=("meaning", "system"),
    ))
