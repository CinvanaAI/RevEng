"""Compression utilities for collapsing lower-layer labels and evidence lists
into concise higher-layer representations."""
from __future__ import annotations

from typing import Any


def _get_label(record: Any) -> str | None:
    if isinstance(record, dict):
        return record.get("label")
    return getattr(record, "label", None)


def compress_label(records: list[Any], *, max_length: int = 200) -> str:
    """Join record labels with '; ', truncating to max_length with '...'."""
    labels = [lbl for r in records if (lbl := _get_label(r))]
    if not labels:
        return ""
    joined = "; ".join(labels)
    if len(joined) <= max_length:
        return joined
    truncated = joined[:max_length - 3]
    # Don't cut mid-word
    last_sep = truncated.rfind(";")
    if last_sep > max_length // 2:
        truncated = truncated[:last_sep]
    return truncated.rstrip() + "..."


def compress_evidence_refs(refs: list[str], *, limit: int = 20) -> list[str]:
    """Return at most `limit` evidence refs, preserving order."""
    return refs[:limit]


def is_pass_through(subsystems: list[Any]) -> bool:
    """True when the target is so small that higher-layer labels are trivially
    identical to lower-layer content — single subsystem containing a single module."""
    if len(subsystems) != 1:
        return False
    sub = subsystems[0]
    ids = (
        sub.get("module_summary_ids") if isinstance(sub, dict)
        else getattr(sub, "module_summary_ids", [])
    )
    return len(ids) <= 1
