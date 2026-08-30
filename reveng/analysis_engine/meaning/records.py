"""Typed meaning record dataclasses for each layer in the RevEng meaning stack.

Layer order (bottom to top):
  AbilityRecord            — atomic capabilities
  ActionRecord             — ability at a specific call site
  FunctionMeaningRecord    — meaning of a whole function (aggregates actions)
  FilePurposeRecord        — what a file IS (structure + abilities, early)
  FileBehaviorRecord       — what a file DOES (realized actions, late)
  WorkflowRecord           — end-to-end chains (parallel output, not in linear stack)
  ModuleSummaryRecord      — [PROVISIONAL] cluster grouping approximation
  SubsystemSummaryRecord   — [PROVISIONAL] path-prefix grouping approximation
  SystemSummaryRecord      — whole-program summary

All records carry a `derivation` field. Serialise with `to_dict(record)`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from reveng.analysis_engine.meaning.confidence import ConfidenceLevel
from reveng.analysis_engine.meaning.derivation import DerivationRecord
from reveng.analysis_engine.meaning.dimensions import DimensionID


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _convert_enums(obj: Any) -> Any:
    """Recursively convert Enum members to their .value so json.dumps works."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _convert_enums(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_enums(i) for i in obj]
    return obj


def to_dict(record: Any) -> dict:
    """Serialise a meaning record dataclass to a plain JSON-compatible dict."""
    return _convert_enums(asdict(record))


# ---------------------------------------------------------------------------
# Layer 1: AbilityRecord
# ---------------------------------------------------------------------------

@dataclass
class AbilityRecord:
    """Atomic capability the code can perform, independent of context."""
    ability_id: str              # e.g. "can_emit_text_output"
    label: str                   # e.g. "can emit text output"
    dimension: DimensionID
    evidence_refs: list[str]     # format: "file_path::scope::lineno::detail"
    confidence: ConfidenceLevel
    inferred: bool
    source_files: list[str]
    derivation: DerivationRecord


# ---------------------------------------------------------------------------
# Layer 2: ActionRecord
# ---------------------------------------------------------------------------

@dataclass
class ActionRecord:
    """Ability instantiated at a specific call site in a specific function."""
    action_id: str
    label: str                   # "function X in file.py can emit text output"
    ability_id: str
    file_path: str
    function_scope: str
    lineno: int
    evidence_refs: list[str]
    confidence: ConfidenceLevel
    inferred: bool
    derivation: DerivationRecord


# ---------------------------------------------------------------------------
# Layer 3: FunctionMeaningRecord
# ---------------------------------------------------------------------------

# Possible resolution states for a function meaning record.
RESOLUTION_BEHAVIORALLY_RESOLVED = "behaviorally_resolved"
RESOLUTION_STRUCTURALLY_DISCOVERED = "structurally_discovered"

# Behavior class — finer classification within and around resolution_status.
#   behaviorally_resolved   — has own action records; meaning is evidence-backed
#   coordinator             — orchestrates ≥2 callees with few or no own actions
#   thin_wrapper            — 1-2 callees, no own actions, but non-trivial body
#                             (assignments, raises, control_flow, multiple returns)
#   pure_wrapper            — 1-2 callees, no own actions, trivial pass-through body
#   structurally_discovered — known from defined_symbols only; no actions, no callees
BEHAVIOR_CLASS_BEHAVIORALLY_RESOLVED = "behaviorally_resolved"
BEHAVIOR_CLASS_COORDINATOR = "coordinator"
BEHAVIOR_CLASS_THIN_WRAPPER = "thin_wrapper"
BEHAVIOR_CLASS_PURE_WRAPPER = "pure_wrapper"
BEHAVIOR_CLASS_STRUCTURALLY_DISCOVERED = "structurally_discovered"

@dataclass
class FunctionMeaningRecord:
    """Meaning of a single function — aggregates all its actions.

    resolution_status distinguishes two kinds of records:
      "behaviorally_resolved"    — has matching ActionRecords; meaning is evidence-backed
      "structurally_discovered"  — known from defined_symbols only; no action records;
                                   behaviorally unresolved and must not be treated as derived

    behavior_class is a finer classification:
      "behaviorally_resolved"    — direct evidence of own behavior
      "coordinator"              — few own actions but orchestrates many callees
      "pure_wrapper"             — no own actions but delegates to callees that have them
      "structurally_discovered"  — no evidence, no known callees
    """
    function_id: str             # generated stable ID
    label: str
    file_path: str
    function_scope: str
    lineno: int
    end_lineno: int
    action_ids: list[str]
    ability_ids: list[str]
    dimensions: list[DimensionID]
    evidence_refs: list[str]     # propagated (compressed) from contributing action evidence_refs
    confidence: ConfidenceLevel
    inferred: bool
    resolution_status: str       # RESOLUTION_BEHAVIORALLY_RESOLVED or RESOLUTION_STRUCTURALLY_DISCOVERED
    behavior_class: str          # one of the BEHAVIOR_CLASS_* constants above
    derivation: DerivationRecord


# ---------------------------------------------------------------------------
# Layer 4: FilePurposeRecord  (structure + abilities, early)
# ---------------------------------------------------------------------------

@dataclass
class FilePurposeRecord:
    """What this file IS — derived from structure and abilities.
    Does not require ActionRecords; available earlier in the pipeline."""
    file_path: str
    label: str
    ability_ids: list[str]
    dimensions: list[DimensionID]
    evidence_refs: list[str]     # propagated (compressed) from contributing ability evidence_refs
    confidence: ConfidenceLevel
    inferred: bool
    is_test: bool                # True if file_path matches test naming conventions
    derivation: DerivationRecord


# ---------------------------------------------------------------------------
# Layer 5: FileBehaviorRecord  (realized actions, late)
# ---------------------------------------------------------------------------

@dataclass
class FileBehaviorRecord:
    """What this file DOES — derived from realized actions and function meanings."""
    file_path: str
    label: str
    function_meaning_ids: list[str]
    action_ids: list[str]
    ability_ids: list[str]
    dimensions: list[DimensionID]
    evidence_refs: list[str]     # propagated (compressed) from contributing function meaning evidence_refs
    confidence: ConfidenceLevel
    inferred: bool
    is_test: bool                # True if file_path matches test naming conventions
    derivation: DerivationRecord


# ---------------------------------------------------------------------------
# Layer: WorkflowRecord  (parallel output, not in container stack)
# ---------------------------------------------------------------------------

@dataclass
class WorkflowRecord:
    """End-to-end behavior chain derived from flow_map + actions."""
    workflow_id: str
    label: str
    step_action_ids: list[str]
    entry_point: str
    dimensions: list[DimensionID]
    evidence_refs: list[str]
    confidence: ConfidenceLevel
    inferred: bool
    derivation: DerivationRecord


# ---------------------------------------------------------------------------
# Layer 6: ModuleSummaryRecord  [PROVISIONAL in Phase 1]
# ---------------------------------------------------------------------------

@dataclass
class ModuleSummaryRecord:
    """PROVISIONAL: identity derived from cluster grouping heuristics,
    not from resolved semantic module boundaries."""
    module_path: str             # = cluster_id (Phase 1: structural approximation)
    label: str
    file_purpose_ids: list[str]  # FilePurposeRecord file_paths
    file_behavior_ids: list[str] # FileBehaviorRecord file_paths
    dimensions: list[DimensionID]
    evidence_refs: list[str]     # propagated (compressed) from file purpose/behavior evidence_refs
    confidence: ConfidenceLevel
    inferred: bool
    phase1_approximation: bool   # always True in Phase 1
    derivation: DerivationRecord
    semantic_profile: dict[str, Any] = field(default_factory=dict)
    # ^ Augmentation metadata: dimension counts, structural role, ability coverage.
    # Derived from ability/behavior records; never replaces the structural layer.


# ---------------------------------------------------------------------------
# Layer 7: SubsystemSummaryRecord  [PROVISIONAL in Phase 1]
# ---------------------------------------------------------------------------

@dataclass
class SubsystemSummaryRecord:
    """PROVISIONAL: identity derived from path-depth heuristics,
    not from resolved semantic subsystem boundaries."""
    subsystem_id: str
    label: str
    module_summary_ids: list[str]
    dimensions: list[DimensionID]
    evidence_refs: list[str]     # propagated (compressed) from module summary evidence_refs
    confidence: ConfidenceLevel
    inferred: bool
    phase1_approximation: bool   # always True in Phase 1
    derivation: DerivationRecord


# ---------------------------------------------------------------------------
# Layer 8: SystemSummaryRecord
# ---------------------------------------------------------------------------

@dataclass
class SystemSummaryRecord:
    """Whole-program summary, built from validated lower-layer meanings."""
    label: str
    subsystem_summary_ids: list[str]
    dimensions: list[DimensionID]
    evidence_refs: list[str]     # propagated (compressed) from subsystem summary evidence_refs
    confidence: ConfidenceLevel
    inferred: bool
    is_pass_through: bool
    derivation: DerivationRecord


# ---------------------------------------------------------------------------
# MeaningBundle
# ---------------------------------------------------------------------------

@dataclass
class MeaningBundle:
    """All meaning records produced by a single layered breakdown run."""
    ability_records: list[AbilityRecord] = field(default_factory=list)
    action_records: list[ActionRecord] = field(default_factory=list)
    function_meaning_records: list[FunctionMeaningRecord] = field(default_factory=list)
    file_purpose_records: list[FilePurposeRecord] = field(default_factory=list)
    file_behavior_records: list[FileBehaviorRecord] = field(default_factory=list)
    workflow_records: list[WorkflowRecord] = field(default_factory=list)
    module_summary_records: list[ModuleSummaryRecord] = field(default_factory=list)
    subsystem_summary_records: list[SubsystemSummaryRecord] = field(default_factory=list)
    system_summary_record: SystemSummaryRecord | None = None


# ---------------------------------------------------------------------------
# SystemMap — typed assembly artifact for the full meaning output
# ---------------------------------------------------------------------------

@dataclass
class SystemMap:
    """Typed assembly artifact produced by OutputComposer.compose().

    Wraps all meaning record lists + the system summary into one navigable
    structure. Corresponds to spec Section 10.3 assembly artifacts.
    """
    ability_records: list[AbilityRecord] = field(default_factory=list)
    action_records: list[ActionRecord] = field(default_factory=list)
    function_meaning_records: list[FunctionMeaningRecord] = field(default_factory=list)
    file_purpose_records: list[FilePurposeRecord] = field(default_factory=list)
    file_behavior_records: list[FileBehaviorRecord] = field(default_factory=list)
    workflow_records: list[WorkflowRecord] = field(default_factory=list)
    module_summary_records: list[ModuleSummaryRecord] = field(default_factory=list)
    subsystem_summary_records: list[SubsystemSummaryRecord] = field(default_factory=list)
    system_summary_record: SystemSummaryRecord | None = None
    # Output paths written by OutputComposer
    output_paths: dict = field(default_factory=dict)
