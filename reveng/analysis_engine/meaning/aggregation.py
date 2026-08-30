"""Aggregation utilities used by Task Agents to roll up lower-layer records."""
from __future__ import annotations

from typing import Any

from reveng.analysis_engine.meaning.confidence import ConfidenceLevel, min_confidence
from reveng.analysis_engine.meaning.dimensions import DimensionID


def _get_field(record: Any, *names: str) -> Any:
    """Return the first matching field from a dataclass or dict."""
    if isinstance(record, dict):
        for name in names:
            if name in record:
                return record[name]
    else:
        for name in names:
            if hasattr(record, name):
                return getattr(record, name)
    return None


def aggregate_dimensions(records: list[Any]) -> list[DimensionID]:
    """Union of all dimension values across a list of records.

    Handles both DimensionID enum values and their string equivalents
    (for records loaded from cached JSON).
    """
    seen: set[str] = set()
    for record in records:
        dim = _get_field(record, "dimension", "dimensions")
        if dim is None:
            continue
        if isinstance(dim, (list, tuple)):
            items = dim
        else:
            items = [dim]
        for item in items:
            val = item.value if isinstance(item, DimensionID) else str(item)
            seen.add(val)
    # Return as DimensionID where possible, else keep string values
    result: list[DimensionID] = []
    for val in sorted(seen):
        try:
            result.append(DimensionID(val))
        except ValueError:
            pass  # skip unknown dimension strings
    return result


def aggregate_confidence(records: list[Any]) -> ConfidenceLevel:
    """Minimum (weakest) confidence level across a list of records."""
    levels: list[ConfidenceLevel] = []
    for record in records:
        raw = _get_field(record, "confidence")
        if raw is None:
            continue
        if isinstance(raw, ConfidenceLevel):
            levels.append(raw)
        else:
            try:
                levels.append(ConfidenceLevel(raw))
            except ValueError:
                pass
    return min_confidence(levels)


def aggregate_ability_ids(records: list[Any]) -> list[str]:
    """Deduplicated union of ability_id / ability_ids fields across records."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for record in records:
        ids = _get_field(record, "ability_ids", "ability_id")
        if ids is None:
            continue
        if isinstance(ids, str):
            ids = [ids]
        for aid in ids:
            if aid not in seen_set:
                seen_set.add(aid)
                seen.append(aid)
    return seen


def aggregate_action_ids(records: list[Any]) -> list[str]:
    """Deduplicated union of action_id / action_ids fields across records."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for record in records:
        ids = _get_field(record, "action_ids", "action_id")
        if ids is None:
            continue
        if isinstance(ids, str):
            ids = [ids]
        for aid in ids:
            if aid not in seen_set:
                seen_set.add(aid)
                seen.append(aid)
    return seen


def aggregate_function_ids(records: list[Any]) -> list[str]:
    """Deduplicated union of function_id / function_meaning_ids fields across records."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for record in records:
        ids = _get_field(record, "function_meaning_ids", "function_id")
        if ids is None:
            continue
        if isinstance(ids, str):
            ids = [ids]
        for fid in ids:
            if fid not in seen_set:
                seen_set.add(fid)
                seen.append(fid)
    return seen
