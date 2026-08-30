"""reveng.meaning — Core Schema Layer for RevEng layered meaning extraction.

Public surface:
  Enums:      LayerID, DimensionID, ConfidenceLevel, InferencePolicy, DerivationBasis
  Constants:  LAYER_ORDER, PHASE1_PROVISIONAL_LAYERS, DIMENSION_LABELS, CONTRACT_REGISTRY
  Dataclasses: ConfidencePolicy, DerivationRecord, LayerContract
  Records:    AbilityRecord, ActionRecord, FunctionMeaningRecord,
              FilePurposeRecord, FileBehaviorRecord, WorkflowRecord,
              ModuleSummaryRecord, SubsystemSummaryRecord, SystemSummaryRecord,
              MeaningBundle, SystemMap
  Evidence:   EnrichedFileRecord, ClusterRecord, FlowRecord, SymbolRecord,
              EnrichedCallRecord, EnrichedImportRecord
  Constants:  RESOLUTION_BEHAVIORALLY_RESOLVED, RESOLUTION_STRUCTURALLY_DISCOVERED
  Functions:  to_dict, aggregate_dimensions, aggregate_confidence,
              aggregate_ability_ids, aggregate_action_ids, aggregate_function_ids,
              compress_label, compress_evidence_refs, is_pass_through, min_confidence
"""

from reveng.analysis_engine.meaning.layers import LayerID, LAYER_ORDER, PHASE1_PROVISIONAL_LAYERS
from reveng.analysis_engine.meaning.dimensions import DimensionID, DIMENSION_LABELS
from reveng.analysis_engine.meaning.confidence import ConfidenceLevel, InferencePolicy, ConfidencePolicy, min_confidence
from reveng.analysis_engine.meaning.derivation import DerivationBasis, DerivationRecord
from reveng.analysis_engine.meaning.records import (
    AbilityRecord,
    ActionRecord,
    FunctionMeaningRecord,
    FilePurposeRecord,
    FileBehaviorRecord,
    WorkflowRecord,
    ModuleSummaryRecord,
    SubsystemSummaryRecord,
    SystemSummaryRecord,
    MeaningBundle,
    SystemMap,
    RESOLUTION_BEHAVIORALLY_RESOLVED,
    RESOLUTION_STRUCTURALLY_DISCOVERED,
    to_dict,
)
from reveng.analysis_engine.meaning.evidence import (
    EnrichedFileRecord,
    ClusterRecord,
    FlowRecord,
    SymbolRecord,
    EnrichedCallRecord,
    EnrichedImportRecord,
)
from reveng.analysis_engine.meaning.contracts import LayerContract, CONTRACT_REGISTRY
from reveng.analysis_engine.meaning.aggregation import (
    aggregate_dimensions,
    aggregate_confidence,
    aggregate_ability_ids,
    aggregate_action_ids,
    aggregate_function_ids,
)
from reveng.analysis_engine.meaning.compression import compress_label, compress_evidence_refs, is_pass_through

__all__ = [
    # Enums
    "LayerID", "DimensionID", "ConfidenceLevel", "InferencePolicy", "DerivationBasis",
    # Constants
    "LAYER_ORDER", "PHASE1_PROVISIONAL_LAYERS", "DIMENSION_LABELS", "CONTRACT_REGISTRY",
    "RESOLUTION_BEHAVIORALLY_RESOLVED", "RESOLUTION_STRUCTURALLY_DISCOVERED",
    # Dataclasses
    "ConfidencePolicy", "DerivationRecord", "LayerContract",
    # Records
    "AbilityRecord", "ActionRecord", "FunctionMeaningRecord",
    "FilePurposeRecord", "FileBehaviorRecord", "WorkflowRecord",
    "ModuleSummaryRecord", "SubsystemSummaryRecord", "SystemSummaryRecord",
    "MeaningBundle", "SystemMap",
    # Evidence TypedDicts
    "EnrichedFileRecord", "ClusterRecord", "FlowRecord", "SymbolRecord",
    "EnrichedCallRecord", "EnrichedImportRecord",
    # Serialisation
    "to_dict",
    # Aggregation
    "aggregate_dimensions", "aggregate_confidence",
    "aggregate_ability_ids", "aggregate_action_ids", "aggregate_function_ids",
    # Compression
    "compress_label", "compress_evidence_refs", "is_pass_through",
    # Confidence
    "min_confidence",
]
