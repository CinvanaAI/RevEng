"""FilePurposeAgent — derives FilePurposeRecords from AbilityRecords.

What a file IS — derived from structure and abilities.
Does not depend on ActionRecords or FunctionMeaningRecords; available earlier.
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
from reveng.analysis_engine.meaning.aggregation import aggregate_confidence, aggregate_dimensions
from reveng.analysis_engine.meaning.compression import compress_evidence_refs
from reveng.analysis_engine.meaning.confidence import ConfidenceLevel, _CONFIDENCE_RANK
from reveng.analysis_engine.meaning.derivation import DerivationBasis
from reveng.analysis_engine.meaning.layers import LayerID
from reveng.analysis_engine.meaning.records import FilePurposeRecord, to_dict

PACK_ID = "reveng.pack.meaning_layer"
KIND = "meaning.file_purpose_records.v1"


_ACTIVE_BEHAVIOR_CLASSES = frozenset(("behaviorally_resolved", "coordinator", "thin_wrapper"))


def _file_behavioral_density(function_meanings: list[dict[str, Any]]) -> dict[str, float]:
    """Return {file_path: fraction_of_active_behavior_classes} for Phase 12 density floor."""
    from collections import Counter as _Counter
    file_total: dict[str, int] = {}
    file_active: dict[str, int] = {}
    for rec in function_meanings:
        fp = rec.get("file_path", "")
        if not fp:
            continue
        file_total[fp] = file_total.get(fp, 0) + 1
        if rec.get("behavior_class", "") in _ACTIVE_BEHAVIOR_CLASSES:
            file_active[fp] = file_active.get(fp, 0) + 1
    return {
        fp: file_active.get(fp, 0) / total
        for fp, total in file_total.items()
        if total > 0
    }


def _density_confidence_floor(
    current: ConfidenceLevel,
    density: float,
) -> ConfidenceLevel:
    """Apply Phase 12 density floor: raise confidence based on active function fraction."""
    current_rank = _CONFIDENCE_RANK[current]
    if density >= 0.50:
        # ≥50% active functions → at least MEDIUM
        if current_rank < _CONFIDENCE_RANK[ConfidenceLevel.MEDIUM]:
            return ConfidenceLevel.MEDIUM
    elif density >= 0.25:
        # ≥25% active functions → at least LOW
        if current_rank < _CONFIDENCE_RANK[ConfidenceLevel.LOW]:
            return ConfidenceLevel.LOW
    return current


def _derive_file_purposes(
    abilities: list[dict[str, Any]],
    enriched: dict[str, Any],
    function_meanings: list[dict[str, Any]] | None = None,
) -> list[FilePurposeRecord]:
    file_index = _build_file_index(enriched)
    records: list[FilePurposeRecord] = []

    # Build a per-file ability index: file_path -> list of ability dicts
    file_abilities: dict[str, list[dict[str, Any]]] = {fp: [] for fp in file_index}
    for ability in abilities:
        for fp in ability.get("source_files", []):
            if fp in file_abilities:
                file_abilities[fp].append(ability)

    # Phase 12: per-file behavioral density for confidence floor
    density_map: dict[str, float] = {}
    if function_meanings:
        density_map = _file_behavioral_density(function_meanings)

    for file_path, file_record in file_index.items():
        if "parse_error" in file_record:
            continue

        matched = file_abilities.get(file_path, [])
        ability_ids = [a["ability_id"] for a in matched]
        dimensions = aggregate_dimensions(matched)

        # Build a descriptive label from defined symbols + dimensions
        symbol_names = [
            s.get("name", "")
            for s in file_record.get("defined_symbols", [])
            if s.get("type") in ("function", "method", "async_function", "class")
        ][:4]

        if symbol_names and dimensions:
            dim_str = ", ".join(d.value if hasattr(d, "value") else str(d) for d in dimensions[:3])
            label = f"defines {', '.join(symbol_names)}; {dim_str}"
        elif symbol_names:
            label = f"defines {', '.join(symbol_names)}"
        elif dimensions:
            dim_str = ", ".join(d.value if hasattr(d, "value") else str(d) for d in dimensions[:3])
            label = f"file with {dim_str}"
        else:
            label = f"file {file_path}"

        if matched:
            confidence = aggregate_confidence(matched)
            inferred = False
            deriv_notes = f"aggregated {len(ability_ids)} abilities for {file_path}"
        else:
            confidence = ConfidenceLevel.LOW
            inferred = True
            deriv_notes = (
                f"no matching ability records for {file_path}; "
                "file purpose inferred from structure only"
            )

        # Phase 12: apply density-weighted confidence floor
        density = density_map.get(file_path, 0.0)
        floored = _density_confidence_floor(confidence, density)
        if floored != confidence:
            confidence = floored
            deriv_notes += f"; confidence raised to {confidence.value} by behavioral density ({density:.0%} active functions)"

        # Only keep evidence refs that originate from this file (format: "file_path::...")
        evidence_refs = compress_evidence_refs(
            [ref for a in matched for ref in a.get("evidence_refs", [])
             if ref.startswith(file_path + "::")]
        )

        records.append(FilePurposeRecord(
            file_path=file_path,
            label=label,
            ability_ids=ability_ids,
            dimensions=dimensions,
            evidence_refs=evidence_refs,
            confidence=confidence,
            inferred=inferred,
            is_test=_is_test_file(file_path),
            derivation=_make_derivation(
                DerivationBasis.AGGREGATION,
                source_layer=LayerID.ABILITY,
                source_ids=ability_ids,
                notes=deriv_notes,
            ),
        ))

    return records


def file_purpose_records_json_path(output_dir: Path) -> Path:
    return output_dir / "meaning" / "file_purpose_records.json"


def _derive_file_purposes_capability(context: CapabilityContext) -> dict[str, Any]:
    path = file_purpose_records_json_path(context.runtime.output_dir)

    if context.cache_ready(path, output_name="file_purpose_records"):
        ref = context.load_cached_json_artifact(KIND, path, views={}, metadata={"cached": True})
        data = context.read(ref)
        return {
            "file_purpose_records": ref,
            "file_purpose_records_path": str(path),
            "file_purpose_count": len(data) if isinstance(data, list) else 0,
            "cached": True,
        }

    abilities = context.read_input("ability_records")
    enriched = context.read_input("enriched_file_breakdowns")
    function_meanings_raw = context.read_input("function_meaning_records")

    if not isinstance(abilities, list):
        abilities = list(abilities) if abilities else []
    function_meanings: list[dict] = []
    if function_meanings_raw:
        fm = function_meanings_raw if isinstance(function_meanings_raw, list) else list(function_meanings_raw)
        function_meanings = fm

    records = _derive_file_purposes(abilities, enriched, function_meanings)
    data = [to_dict(r) for r in records]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ref = context.record_artifact(KIND, data, path=path)
    return {
        "file_purpose_records": ref,
        "file_purpose_records_path": str(path),
        "file_purpose_count": len(data),
        "cached": False,
    }


def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="meaning.files.purpose",
        pack_id=PACK_ID,
        version="1",
        display_name="Derive File Purpose Records",
        description="Derive FilePurposeRecords from ability records and enriched file breakdowns (structure-based, early).",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("ability_records", "enriched_file_breakdowns", "function_meaning_records"),
            output=("file_purpose_records", "file_purpose_records_path", "file_purpose_count", "cached"),
        ),
        implementation_logic=_derive_file_purposes_capability,
        tags=("meaning", "file", "purpose"),
    ))
