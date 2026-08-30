"""System-level meaning breakdown workflow.

Full parallelized pipeline from abilities to system summary.

Dependency graph:
  abilities.extract
      └─ actions.derive ──── functions.derive ──── files.purpose ──────────────┐
                                              ├─── files.behavior ──────────────┤
                                              └─── workflows.derive ────────────┤
                                                                                 ↓
                                                                      modules.summarize
                                                                                 ↓
                                                                    subsystems.summarize
                                                                                 ↓
                                                                     system.summarize
"""
from __future__ import annotations

from typing import Any

from reveng.coordination.execution import AgenticExecutor


def run_system_breakdown(executor: AgenticExecutor, base: dict[str, Any]) -> dict[str, Any]:
    """Run the full system-level meaning breakdown with maximum parallelism."""

    # Step 1: abilities (required by all downstream)
    ab = executor.invoke("meaning.abilities.extract", {
        "enriched_file_breakdowns": base["enriched_file_breakdowns"],
        "relation_map": base["relation_map"],
    })

    # Step 2: actions (depends on abilities)
    ac_result = executor.invoke("meaning.actions.derive", {
        "ability_records": ab["ability_records"],
        "enriched_file_breakdowns": base["enriched_file_breakdowns"],
    })

    # Step 3: function meanings (depends on actions)
    fm = executor.invoke("meaning.functions.derive", {
        "action_records": ac_result["action_records"],
        "enriched_file_breakdowns": base["enriched_file_breakdowns"],
        "relation_map": base["relation_map"],
    })

    # Step 4: parallel — file_purpose + file_behavior + workflow_records
    # file_purpose now depends on function_meaning_records for density-weighted confidence
    [fp_result, fb_result, wr_result] = executor.invoke_parallel([
        ("meaning.files.purpose", {
            "ability_records": ab["ability_records"],
            "enriched_file_breakdowns": base["enriched_file_breakdowns"],
            "function_meaning_records": fm["function_meaning_records"],
        }),
        ("meaning.files.behavior", {
            "function_meaning_records": fm["function_meaning_records"],
            "action_records": ac_result["action_records"],
            "enriched_file_breakdowns": base["enriched_file_breakdowns"],
        }),
        ("meaning.workflows.derive", {
            "action_records": ac_result["action_records"],
            "flow_map": base["flow_map"],
            "enriched_file_breakdowns": base["enriched_file_breakdowns"],
        }),
    ], max_workers=3)

    # Step 5: module summaries (depend on both file_purpose and file_behavior)
    ms = executor.invoke("meaning.modules.summarize", {
        "file_purpose_records": fp_result["file_purpose_records"],
        "file_behavior_records": fb_result["file_behavior_records"],
        "cluster_map": base["cluster_map"],
    })

    # Step 6: subsystem summaries
    ss = executor.invoke("meaning.subsystems.summarize", {
        "module_summary_records": ms["module_summary_records"],
        "cluster_map": base["cluster_map"],
    })

    # Step 7: system summary
    sys_r = executor.invoke("meaning.system.summarize", {
        "subsystem_summary_records": ss["subsystem_summary_records"],
    })

    return {**ab, **fp_result, **ac_result, **fm, **fb_result, **wr_result, **ms, **ss, **sys_r}
