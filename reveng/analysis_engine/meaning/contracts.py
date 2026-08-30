"""Formal layer contracts defining evidence requirements, aggregation rules,
and compression policies for each meaning layer."""
from __future__ import annotations

from dataclasses import dataclass, field

from reveng.analysis_engine.meaning.confidence import ConfidencePolicy, InferencePolicy
from reveng.analysis_engine.meaning.layers import LayerID, PHASE1_PROVISIONAL_LAYERS
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
)


@dataclass(frozen=True)
class LayerContract:
    layer_id: LayerID
    unit_type: str
    description_scope: str
    required_evidence_types: tuple[str, ...]
    optional_evidence_types: tuple[str, ...]
    allowed_lower_layer_inputs: tuple[LayerID, ...]
    output_schema: type
    aggregation_rules: str
    compression_rules: str
    pass_through_allowed: bool
    confidence_policy: ConfidencePolicy
    inference_policy: InferencePolicy
    phase1_approximation: bool = False


CONTRACT_REGISTRY: dict[LayerID, LayerContract] = {
    LayerID.ABILITY: LayerContract(
        layer_id=LayerID.ABILITY,
        unit_type="atomic_capability",
        description_scope="A single thing the code can do, independent of context.",
        required_evidence_types=("enriched_file_breakdowns",),
        optional_evidence_types=("relation_map",),
        allowed_lower_layer_inputs=(),
        output_schema=AbilityRecord,
        aggregation_rules="Deduplicate by ability_id across all source files.",
        compression_rules="No compression needed; atomic units.",
        pass_through_allowed=False,
        confidence_policy=ConfidencePolicy(
            min_evidence_count=1,
            inference_policy=InferencePolicy.ALLOW_HEURISTIC,
            pass_through_allowed=False,
        ),
        inference_policy=InferencePolicy.ALLOW_HEURISTIC,
    ),
    LayerID.ACTION: LayerContract(
        layer_id=LayerID.ACTION,
        unit_type="call_site_instantiation",
        description_scope="An ability instantiated at a specific function scope and call site.",
        required_evidence_types=("ability_records", "enriched_file_breakdowns"),
        optional_evidence_types=(),
        allowed_lower_layer_inputs=(LayerID.ABILITY,),
        output_schema=ActionRecord,
        aggregation_rules="One ActionRecord per (file_path, function_scope, ability_id) triple.",
        compression_rules="No compression; each record is already minimal.",
        pass_through_allowed=False,
        confidence_policy=ConfidencePolicy(
            min_evidence_count=1,
            inference_policy=InferencePolicy.ALLOW_HEURISTIC,
            pass_through_allowed=False,
        ),
        inference_policy=InferencePolicy.ALLOW_HEURISTIC,
    ),
    LayerID.FUNCTION_MEANING: LayerContract(
        layer_id=LayerID.FUNCTION_MEANING,
        unit_type="function_level_meaning",
        description_scope="Meaning of one function, aggregated from its actions.",
        required_evidence_types=("action_records", "enriched_file_breakdowns"),
        optional_evidence_types=("relation_map",),
        allowed_lower_layer_inputs=(LayerID.ACTION,),
        output_schema=FunctionMeaningRecord,
        aggregation_rules=(
            "Group ActionRecords by (file_path, function_scope). "
            "Also emit structurally_discovered records for functions with no actions."
        ),
        compression_rules=(
            "Label uses function name + top-2 ability labels. "
            "Structurally-discovered records carry resolution_status='structurally_discovered'."
        ),
        pass_through_allowed=True,
        confidence_policy=ConfidencePolicy(
            min_evidence_count=0,
            inference_policy=InferencePolicy.ALLOW_HEURISTIC,
            pass_through_allowed=True,
        ),
        inference_policy=InferencePolicy.ALLOW_HEURISTIC,
    ),
    LayerID.FILE_PURPOSE: LayerContract(
        layer_id=LayerID.FILE_PURPOSE,
        unit_type="file_purpose",
        description_scope="What a file IS — its structural role and ability profile.",
        required_evidence_types=("ability_records", "enriched_file_breakdowns"),
        optional_evidence_types=(),
        allowed_lower_layer_inputs=(LayerID.ABILITY,),
        output_schema=FilePurposeRecord,
        aggregation_rules="One record per file; aggregate all matching ability_ids.",
        compression_rules="Label from symbol names + top dimensions.",
        pass_through_allowed=True,
        confidence_policy=ConfidencePolicy(
            min_evidence_count=0,
            inference_policy=InferencePolicy.ALLOW_HEURISTIC,
            pass_through_allowed=True,
        ),
        inference_policy=InferencePolicy.ALLOW_HEURISTIC,
    ),
    LayerID.FILE_BEHAVIOR: LayerContract(
        layer_id=LayerID.FILE_BEHAVIOR,
        unit_type="file_behavior",
        description_scope="What a file DOES — its realized behavioral patterns.",
        required_evidence_types=("function_meaning_records", "action_records", "enriched_file_breakdowns"),
        optional_evidence_types=(),
        allowed_lower_layer_inputs=(LayerID.FUNCTION_MEANING, LayerID.ACTION),
        output_schema=FileBehaviorRecord,
        aggregation_rules=(
            "One record per file; aggregate behaviorally_resolved FunctionMeaningRecords only. "
            "If all functions are structurally_discovered, confidence degrades to UNKNOWN."
        ),
        compression_rules="Label from function labels (behavioral form).",
        pass_through_allowed=True,
        confidence_policy=ConfidencePolicy(
            min_evidence_count=0,
            inference_policy=InferencePolicy.ALLOW_HEURISTIC,
            pass_through_allowed=True,
        ),
        inference_policy=InferencePolicy.ALLOW_HEURISTIC,
    ),
    LayerID.WORKFLOW: LayerContract(
        layer_id=LayerID.WORKFLOW,
        unit_type="workflow_chain",
        description_scope="End-to-end behavior chain from an entrypoint through its reachable actions.",
        required_evidence_types=("action_records", "flow_map"),
        optional_evidence_types=(),
        allowed_lower_layer_inputs=(LayerID.ACTION,),
        output_schema=WorkflowRecord,
        aggregation_rules="One WorkflowRecord per flow_map flow entry.",
        compression_rules="step_action_ids ordered by BFS depth.",
        pass_through_allowed=True,
        confidence_policy=ConfidencePolicy(
            min_evidence_count=0,
            inference_policy=InferencePolicy.ALLOW_HEURISTIC,
            pass_through_allowed=True,
        ),
        inference_policy=InferencePolicy.ALLOW_HEURISTIC,
    ),
    LayerID.MODULE_SUMMARY: LayerContract(
        layer_id=LayerID.MODULE_SUMMARY,
        unit_type="module_summary",
        description_scope=(
            "[PROVISIONAL Phase 1] Structural grouping of files into a cluster. "
            "Identity derived from cluster heuristics, not semantic module boundaries."
        ),
        required_evidence_types=("file_purpose_records", "cluster_map"),
        optional_evidence_types=("file_behavior_records",),
        allowed_lower_layer_inputs=(LayerID.FILE_PURPOSE, LayerID.FILE_BEHAVIOR),
        output_schema=ModuleSummaryRecord,
        aggregation_rules="One record per cluster; aggregate file purpose + behavior records.",
        compression_rules="compress_label() from member file labels.",
        pass_through_allowed=True,
        confidence_policy=ConfidencePolicy(
            min_evidence_count=0,
            inference_policy=InferencePolicy.ALLOW_HEURISTIC,
            pass_through_allowed=True,
        ),
        inference_policy=InferencePolicy.ALLOW_HEURISTIC,
        phase1_approximation=True,
    ),
    LayerID.SUBSYSTEM_SUMMARY: LayerContract(
        layer_id=LayerID.SUBSYSTEM_SUMMARY,
        unit_type="subsystem_summary",
        description_scope=(
            "[PROVISIONAL Phase 1] Structural grouping of modules by top-level path prefix. "
            "Identity derived from path heuristics, not semantic subsystem boundaries."
        ),
        required_evidence_types=("module_summary_records", "cluster_map"),
        optional_evidence_types=(),
        allowed_lower_layer_inputs=(LayerID.MODULE_SUMMARY,),
        output_schema=SubsystemSummaryRecord,
        aggregation_rules="One record per top-level path prefix; aggregate module summaries.",
        compression_rules="compress_label() from module labels.",
        pass_through_allowed=True,
        confidence_policy=ConfidencePolicy(
            min_evidence_count=0,
            inference_policy=InferencePolicy.ALLOW_HEURISTIC,
            pass_through_allowed=True,
        ),
        inference_policy=InferencePolicy.ALLOW_HEURISTIC,
        phase1_approximation=True,
    ),
    LayerID.SYSTEM: LayerContract(
        layer_id=LayerID.SYSTEM,
        unit_type="system_summary",
        description_scope="Whole-program explanation, built from validated lower-layer meanings.",
        required_evidence_types=("subsystem_summary_records",),
        optional_evidence_types=(),
        allowed_lower_layer_inputs=(LayerID.SUBSYSTEM_SUMMARY,),
        output_schema=SystemSummaryRecord,
        aggregation_rules="One record per run; aggregate all subsystem summaries.",
        compression_rules="compress_label(); is_pass_through=True for trivial targets.",
        pass_through_allowed=True,
        confidence_policy=ConfidencePolicy(
            min_evidence_count=0,
            inference_policy=InferencePolicy.PASS_THROUGH,
            pass_through_allowed=True,
        ),
        inference_policy=InferencePolicy.PASS_THROUGH,
    ),
}
