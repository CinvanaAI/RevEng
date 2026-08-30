"""File-level meaning breakdown workflow.

Extracts abilities, derives file purposes (early), derives actions,
then function meanings and file behaviors.
"""
from __future__ import annotations

from typing import Any

from reveng.coordination.execution import AgenticExecutor


def run_file_breakdown(executor: AgenticExecutor, base: dict[str, Any]) -> dict[str, Any]:
    """Run the file-level meaning breakdown over a base analysis result."""
    ab = executor.invoke("meaning.abilities.extract", {
        "enriched_file_breakdowns": base["enriched_file_breakdowns"],
        "relation_map": base["relation_map"],
    })

    # file_purpose depends only on abilities (runs first, early output)
    fp = executor.invoke("meaning.files.purpose", {
        "ability_records": ab["ability_records"],
        "enriched_file_breakdowns": base["enriched_file_breakdowns"],
    })

    ac = executor.invoke("meaning.actions.derive", {
        "ability_records": ab["ability_records"],
        "enriched_file_breakdowns": base["enriched_file_breakdowns"],
    })

    fm = executor.invoke("meaning.functions.derive", {
        "action_records": ac["action_records"],
        "enriched_file_breakdowns": base["enriched_file_breakdowns"],
        "relation_map": base["relation_map"],
    })

    fb = executor.invoke("meaning.files.behavior", {
        "function_meaning_records": fm["function_meaning_records"],
        "action_records": ac["action_records"],
        "enriched_file_breakdowns": base["enriched_file_breakdowns"],
    })

    return {**ab, **fp, **ac, **fm, **fb}
