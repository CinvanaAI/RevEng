from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reveng.analysis_engine.meaning.layers import LayerID


class DerivationBasis(str, Enum):
    DIRECT_CALL_PATTERN      = "direct_call_pattern"       # matched a call record to an ability pattern
    DECORATOR_INFERENCE      = "decorator_inference"       # inferred from decorator text
    STRUCTURAL_INFERENCE     = "structural_inference"      # inferred from class hierarchy, main blocks, etc.
    IMPORT_INFERENCE         = "import_inference"          # inferred from import statements (file-level floor)
    SIDE_EFFECT_OBSERVATION  = "side_effect_observation"   # from observed_side_effects in enriched breakdown
    FLOW_MEMBERSHIP          = "flow_membership"           # derived from flow_map BFS traversal
    AGGREGATION              = "aggregation"               # rolled up from lower-layer records
    GROUPING                 = "grouping"                  # provisional: cluster/path structural grouping
    PASS_THROUGH_COMPRESSION = "pass_through_compression"  # trivial target: lower record promoted unchanged
    MANUAL                   = "manual"                    # injected externally (future)


@dataclass
class DerivationRecord:
    basis: DerivationBasis
    source_layer: str | None          # LayerID value (str) of the lower layer this came from
    source_ids: list[str]             # IDs of lower-layer records that contributed
    notes: str                        # e.g. "pattern: print()" or "cluster: reveng/packs"
    phase1_approximation: bool        # True for MODULE_SUMMARY, SUBSYSTEM_SUMMARY in Phase 1
