from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Paths from python_static pack
# ---------------------------------------------------------------------------

def inventory_json_path(output_dir: Path) -> Path:
    return output_dir / "repo_inventory.json"


def relation_map_json_path(output_dir: Path) -> Path:
    return output_dir / "relation_map.json"


def file_breakdowns_json_path(output_dir: Path) -> Path:
    return output_dir / "file_breakdowns.json"


def enriched_json_path(output_dir: Path) -> Path:
    return output_dir / "enriched_file_breakdowns.json"


def cluster_map_json_path(output_dir: Path) -> Path:
    return output_dir / "subsystem_map.json"


def flow_map_json_path(output_dir: Path) -> Path:
    return output_dir / "flow_map.json"


# ---------------------------------------------------------------------------
# Paths from llm_narration pack
# ---------------------------------------------------------------------------

def ai_file_explanations_json_path(output_dir: Path) -> Path:
    return output_dir / "ai_file_explanations.json"


def ai_cluster_summaries_json_path(output_dir: Path) -> Path:
    return output_dir / "ai_cluster_summaries.json"


def ai_flow_explanations_json_path(output_dir: Path) -> Path:
    return output_dir / "ai_flow_explanations.json"


def ai_repo_summary_json_path(output_dir: Path) -> Path:
    return output_dir / "ai_repo_summary.json"


# ---------------------------------------------------------------------------
# Paths from reporting pack
# ---------------------------------------------------------------------------

def repo_dossier_json_path(output_dir: Path) -> Path:
    return Path(output_dir) / "repo_dossier.json"


def validation_report_json_path(output_dir: Path) -> Path:
    return Path(output_dir) / "validation_report.json"


def unknowns_json_path(output_dir: Path) -> Path:
    return Path(output_dir) / "unknowns.json"


# ---------------------------------------------------------------------------
# Agent workflow output paths
# ---------------------------------------------------------------------------

def agent_workflow_output_dir(agent_id: str, run_id: str) -> Path:
    """Return the per-run output directory for an agent workflow execution."""
    return Path("output") / "agents" / agent_id / "runs" / run_id
