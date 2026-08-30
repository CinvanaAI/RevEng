"""ActionMeaningAgent — derives ActionRecords from AbilityRecords.

For each ability, finds the specific (file, function_scope) pairs where it is
instantiated, producing one ActionRecord per unique instantiation site.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reveng.analysis_engine.agentic.tasks.functions import (
    _build_file_index,
    _generate_id,
    _make_derivation,
    _parse_evidence_ref,
    _resolve_function_scope,
    _scope_display,
)
from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.analysis_engine.meaning.confidence import ConfidenceLevel
from reveng.analysis_engine.meaning.derivation import DerivationBasis
from reveng.analysis_engine.meaning.layers import LayerID
from reveng.analysis_engine.meaning.records import ActionRecord, to_dict

PACK_ID = "reveng.pack.meaning_layer"
KIND = "meaning.action_records.v1"


def _derive_actions(
    abilities: list[dict[str, Any]],
    enriched: dict[str, Any],
) -> list[ActionRecord]:
    file_index = _build_file_index(enriched)

    # Accumulator: action_id → dict of accumulated fields.
    # Multiple evidence_refs for the same (file, scope, ability) are merged here
    # rather than discarded, preserving all call-site occurrences.
    accumulator: dict[str, dict[str, Any]] = {}

    for ability in abilities:
        ability_id: str = ability.get("ability_id", "")
        ability_label: str = ability.get("label", "")
        ability_confidence_raw = ability.get("confidence", "medium")
        try:
            ability_confidence = ConfidenceLevel(ability_confidence_raw)
        except ValueError:
            ability_confidence = ConfidenceLevel.MEDIUM

        for ref_str in ability.get("evidence_refs", []):
            parsed = _parse_evidence_ref(ref_str)
            file_path = str(parsed["file_path"])
            scope = str(parsed["scope"])
            lineno_raw = parsed["lineno"]
            lineno = int(lineno_raw) if lineno_raw is not None else 0

            action_id = _generate_id("action", file_path, scope, ability_id)

            # Reduce confidence if scope not in defined symbols
            file_record = file_index.get(file_path)
            base_confidence = (
                _degrade(ability_confidence)
                if file_record and _resolve_function_scope(file_record, scope) is None
                else ability_confidence
            )

            if action_id not in accumulator:
                accumulator[action_id] = {
                    "action_id": action_id,
                    "ability_id": ability_id,
                    "ability_label": ability_label,
                    "file_path": file_path,
                    "scope": scope,
                    "lineno": lineno,
                    "evidence_refs": [],
                    "best_confidence": base_confidence,
                }
            entry = accumulator[action_id]
            entry["evidence_refs"].append(ref_str)
            # Upgrade best_confidence if this occurrence is higher
            if _confidence_rank(base_confidence) > _confidence_rank(entry["best_confidence"]):
                entry["best_confidence"] = base_confidence

    records: list[ActionRecord] = []
    for entry in accumulator.values():
        scope = entry["scope"]
        ref_count = len(entry["evidence_refs"])
        confidence = entry["best_confidence"]
        # Multi-occurrence boost: 2+ call sites in the same scope → upgrade one level
        if ref_count >= 2:
            confidence = _upgrade(confidence)

        display = _scope_display(scope)
        label = f"{display} can {entry['ability_label']}"
        if ref_count > 1:
            label += f" [{ref_count}×]"

        records.append(ActionRecord(
            action_id=entry["action_id"],
            label=label,
            ability_id=entry["ability_id"],
            file_path=entry["file_path"],
            function_scope=scope,
            lineno=entry["lineno"],
            evidence_refs=entry["evidence_refs"][:10],
            confidence=confidence,
            inferred=False,
            derivation=_make_derivation(
                DerivationBasis.DIRECT_CALL_PATTERN,
                source_layer=LayerID.ABILITY,
                source_ids=[entry["ability_id"]],
                notes=(
                    f"instantiation of '{entry['ability_id']}' at "
                    f"{entry['file_path']}:{scope}"
                    + (f" ({ref_count} occurrences)" if ref_count > 1 else "")
                ),
            ),
        ))

    return records


_CONFIDENCE_ORDER = [ConfidenceLevel.UNKNOWN, ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH]


def _confidence_rank(level: ConfidenceLevel) -> int:
    try:
        return _CONFIDENCE_ORDER.index(level)
    except ValueError:
        return 0


def _degrade(level: ConfidenceLevel) -> ConfidenceLevel:
    idx = _confidence_rank(level)
    return _CONFIDENCE_ORDER[max(0, idx - 1)]


def _upgrade(level: ConfidenceLevel) -> ConfidenceLevel:
    idx = _confidence_rank(level)
    return _CONFIDENCE_ORDER[min(len(_CONFIDENCE_ORDER) - 1, idx + 1)]


def action_records_json_path(output_dir: Path) -> Path:
    return output_dir / "meaning" / "action_records.json"


def _derive_actions_capability(context: CapabilityContext) -> dict[str, Any]:
    path = action_records_json_path(context.runtime.output_dir)

    if context.cache_ready(path, output_name="action_records"):
        ref = context.load_cached_json_artifact(KIND, path, views={}, metadata={"cached": True})
        data = context.read(ref)
        return {
            "action_records": ref,
            "action_records_path": str(path),
            "action_count": len(data) if isinstance(data, list) else 0,
            "cached": True,
        }

    abilities = context.read_input("ability_records")
    enriched = context.read_input("enriched_file_breakdowns")

    if not isinstance(abilities, list):
        abilities = list(abilities) if abilities else []

    records = _derive_actions(abilities, enriched)
    data = [to_dict(r) for r in records]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ref = context.record_artifact(KIND, data, path=path)
    return {
        "action_records": ref,
        "action_records_path": str(path),
        "action_count": len(data),
        "cached": False,
    }


def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="meaning.actions.derive",
        pack_id=PACK_ID,
        version="1",
        display_name="Derive Action Records",
        description="Derive ActionRecords by instantiating abilities at specific call sites.",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("ability_records", "enriched_file_breakdowns"),
            output=("action_records", "action_records_path", "action_count", "cached"),
        ),
        implementation_logic=_derive_actions_capability,
        tags=("meaning", "action"),
    ))
