"""Observational validation for meaning records.

Checks records against their layer contracts and cross-layer referential
integrity. Returns lists of violation strings — purely observational,
never raises exceptions. Callers should log or surface violations as warnings.
"""
from __future__ import annotations

import logging
from typing import Any

_LOG = logging.getLogger(__name__)

_VALID_CONFIDENCE = frozenset(("high", "medium", "low", "unknown"))


def _check_base(record: dict[str, Any], layer: str, record_id: str) -> list[str]:
    """Checks that apply to every record regardless of layer."""
    v: list[str] = []
    conf = record.get("confidence", "")
    if conf not in _VALID_CONFIDENCE:
        v.append(f"{layer} {record_id}: invalid confidence '{conf}'")
    if record.get("inferred"):
        notes = (record.get("derivation") or {}).get("notes", "")
        if not notes:
            v.append(f"{layer} {record_id}: inferred=True but derivation.notes is empty")
    return v


def validate_meaning_records(system_map_data: dict[str, Any]) -> list[str]:
    """Layer-level contract checks. Returns a list of warning strings."""
    v: list[str] = []

    for r in system_map_data.get("ability_records", []):
        aid = r.get("ability_id", "?")
        v.extend(_check_base(r, "AbilityRecord", aid))
        if not r.get("evidence_refs"):
            v.append(f"AbilityRecord {aid}: evidence_refs is empty")

    for r in system_map_data.get("action_records", []):
        rid = r.get("action_id", "?")
        v.extend(_check_base(r, "ActionRecord", rid))
        if not r.get("evidence_refs"):
            v.append(f"ActionRecord {rid}: evidence_refs is empty")
        if not r.get("ability_id"):
            v.append(f"ActionRecord {rid}: ability_id is missing")

    for r in system_map_data.get("function_meaning_records", []):
        rid = r.get("function_id", "?")
        v.extend(_check_base(r, "FunctionMeaningRecord", rid))
        if (r.get("resolution_status") == "behaviorally_resolved"
                and r.get("confidence") not in ("unknown", "low", None)
                and not r.get("action_ids")):
            v.append(
                f"FunctionMeaningRecord {rid}: behaviorally_resolved / "
                f"confidence={r.get('confidence')} but action_ids is empty"
            )

    for r in system_map_data.get("workflow_records", []):
        rid = r.get("workflow_id", "?")
        v.extend(_check_base(r, "WorkflowRecord", rid))
        if r.get("confidence") in ("medium", "high") and not r.get("step_action_ids"):
            v.append(
                f"WorkflowRecord {rid}: confidence={r.get('confidence')} "
                f"but step_action_ids is empty"
            )

    for r in system_map_data.get("file_purpose_records", []):
        v.extend(_check_base(r, "FilePurposeRecord", r.get("file_path", "?")))

    for r in system_map_data.get("file_behavior_records", []):
        v.extend(_check_base(r, "FileBehaviorRecord", r.get("file_path", "?")))

    return v


def validate_crossrefs(system_map_data: dict[str, Any]) -> list[str]:
    """Cross-layer referential integrity checks. Returns a list of violation strings."""
    v: list[str] = []

    action_ids = {r.get("action_id") for r in system_map_data.get("action_records", [])}
    ability_ids = {r.get("ability_id") for r in system_map_data.get("ability_records", [])}
    function_ids = {r.get("function_id") for r in system_map_data.get("function_meaning_records", [])}

    # FunctionMeaningRecord.action_ids → must exist in action_records
    for r in system_map_data.get("function_meaning_records", []):
        fid = r.get("function_id", "?")
        for aid in r.get("action_ids", []):
            if aid not in action_ids:
                v.append(f"FunctionMeaningRecord {fid}: action_id '{aid}' not in action_records")

    # FilePurposeRecord.ability_ids → must exist in ability_records
    for r in system_map_data.get("file_purpose_records", []):
        fp = r.get("file_path", "?")
        for aid in r.get("ability_ids", []):
            if aid not in ability_ids:
                v.append(f"FilePurposeRecord {fp}: ability_id '{aid}' not in ability_records")

    # FileBehaviorRecord.function_meaning_ids → must exist in function_meaning_records
    for r in system_map_data.get("file_behavior_records", []):
        fp = r.get("file_path", "?")
        for fid in r.get("function_meaning_ids", []):
            if fid not in function_ids:
                v.append(
                    f"FileBehaviorRecord {fp}: function_meaning_id '{fid}' "
                    f"not in function_meaning_records"
                )

    return v


def log_violations(meaning_violations: list[str], crossref_violations: list[str]) -> None:
    """Log all violations as warnings."""
    total = len(meaning_violations) + len(crossref_violations)
    if not total:
        _LOG.info("Meaning validation: 0 violations.")
        return
    _LOG.warning("Meaning validation: %d violation(s).", total)
    for msg in meaning_violations + crossref_violations:
        _LOG.warning("  %s", msg)
