from __future__ import annotations

from enum import Enum


class LayerID(str, Enum):
    ABILITY = "ability"
    ACTION = "action"
    FUNCTION_MEANING = "function_meaning"   # between action and file layers
    FILE_PURPOSE = "file_purpose"           # structure-based, early
    FILE_BEHAVIOR = "file_behavior"         # action-based, late
    WORKFLOW = "workflow"
    MODULE_SUMMARY = "module_summary"       # PROVISIONAL in Phase 1
    SUBSYSTEM_SUMMARY = "subsystem_summary" # PROVISIONAL in Phase 1
    SYSTEM = "system"


LAYER_ORDER: list[LayerID] = [
    LayerID.ABILITY,
    LayerID.ACTION,
    LayerID.FUNCTION_MEANING,
    LayerID.FILE_PURPOSE,
    LayerID.FILE_BEHAVIOR,
    LayerID.MODULE_SUMMARY,
    LayerID.SUBSYSTEM_SUMMARY,
    LayerID.SYSTEM,
]

# Layers whose identity is derived from structural heuristics in Phase 1,
# not from resolved semantic boundaries.
PHASE1_PROVISIONAL_LAYERS: set[LayerID] = {
    LayerID.MODULE_SUMMARY,
    LayerID.SUBSYSTEM_SUMMARY,
}
