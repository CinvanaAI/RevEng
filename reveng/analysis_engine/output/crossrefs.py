"""Cross-reference index builder for the layered meaning output.

Builds a flat index that links records across all meaning layers so that
downstream consumers can navigate from any record to related records.
"""
from __future__ import annotations

from typing import Any


def build_cross_reference_index(system_map_data: dict[str, Any]) -> dict[str, Any]:
    """Build a cross-reference index from the assembled system map data.

    Returns a dict with per-layer lookups:
      ability_to_actions       : ability_id -> [action_id, ...]
      action_to_functions      : action_id  -> [function_id, ...]
      function_to_files        : function_id -> file_path
      file_to_abilities        : file_path  -> [ability_id, ...]
      file_purpose_to_module   : file_path  -> module_path
      file_behavior_to_module  : file_path  -> module_path
      module_to_subsystem      : module_path -> subsystem_id
      ability_to_dimensions    : ability_id -> [dimension, ...]
    """
    index: dict[str, Any] = {
        "ability_to_actions": {},
        "action_to_functions": {},
        "function_to_files": {},
        "file_to_abilities": {},
        "file_purpose_to_module": {},
        "file_behavior_to_module": {},
        "module_to_subsystem": {},
        "ability_to_dimensions": {},
    }

    actions: list[dict[str, Any]] = system_map_data.get("action_records", [])
    function_meanings: list[dict[str, Any]] = system_map_data.get("function_meaning_records", [])
    file_purposes: list[dict[str, Any]] = system_map_data.get("file_purpose_records", [])
    abilities: list[dict[str, Any]] = system_map_data.get("ability_records", [])
    module_summaries: list[dict[str, Any]] = system_map_data.get("module_summary_records", [])
    subsystem_summaries: list[dict[str, Any]] = system_map_data.get("subsystem_summary_records", [])

    # ability_to_dimensions
    for ability in abilities:
        aid = ability.get("ability_id", "")
        dim = ability.get("dimension", "")
        if aid:
            index["ability_to_dimensions"][aid] = [dim] if dim else []

    # ability_to_actions: ability_id -> list of action_ids
    for action in actions:
        aid = action.get("ability_id", "")
        act_id = action.get("action_id", "")
        if aid and act_id:
            index["ability_to_actions"].setdefault(aid, [])
            if act_id not in index["ability_to_actions"][aid]:
                index["ability_to_actions"][aid].append(act_id)

    # action_to_functions: action_id -> list of function_ids
    for fm in function_meanings:
        fid = fm.get("function_id", "")
        for act_id in fm.get("action_ids", []):
            index["action_to_functions"].setdefault(act_id, [])
            if fid not in index["action_to_functions"][act_id]:
                index["action_to_functions"][act_id].append(fid)

    # function_to_files: function_id -> file_path
    for fm in function_meanings:
        fid = fm.get("function_id", "")
        fp = fm.get("file_path", "")
        if fid and fp:
            index["function_to_files"][fid] = fp

    # file_to_abilities: file_path -> list of ability_ids (from file_purpose_records)
    for fp_rec in file_purposes:
        fp = fp_rec.get("file_path", "")
        aids = fp_rec.get("ability_ids", [])
        if fp:
            index["file_to_abilities"][fp] = aids

    # file_purpose_to_module / file_behavior_to_module
    for module in module_summaries:
        module_path = module.get("module_path", "")
        for fp in module.get("file_purpose_ids", []):
            index["file_purpose_to_module"][fp] = module_path
        for fp in module.get("file_behavior_ids", []):
            index["file_behavior_to_module"][fp] = module_path

    # module_to_subsystem
    for subsystem in subsystem_summaries:
        sub_id = subsystem.get("subsystem_id", "")
        for mod_id in subsystem.get("module_summary_ids", []):
            index["module_to_subsystem"][mod_id] = sub_id

    return index
