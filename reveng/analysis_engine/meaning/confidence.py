from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConfidenceLevel(str, Enum):
    HIGH = "high"       # direct static evidence
    MEDIUM = "medium"   # inferred from call patterns
    LOW = "low"         # heuristic or single-source
    UNKNOWN = "unknown" # no evidence


class InferencePolicy(str, Enum):
    REQUIRE_EVIDENCE = "require_evidence"
    ALLOW_HEURISTIC = "allow_heuristic"
    PASS_THROUGH = "pass_through"


@dataclass(frozen=True)
class ConfidencePolicy:
    min_evidence_count: int
    inference_policy: InferencePolicy
    pass_through_allowed: bool


# Canonical ordering for confidence degradation (weakest-wins aggregation).
_CONFIDENCE_RANK: dict[ConfidenceLevel, int] = {
    ConfidenceLevel.HIGH: 3,
    ConfidenceLevel.MEDIUM: 2,
    ConfidenceLevel.LOW: 1,
    ConfidenceLevel.UNKNOWN: 0,
}


def min_confidence(levels: list[ConfidenceLevel]) -> ConfidenceLevel:
    """Return the weakest confidence level in the list."""
    if not levels:
        return ConfidenceLevel.UNKNOWN
    return min(levels, key=lambda c: _CONFIDENCE_RANK[c])
