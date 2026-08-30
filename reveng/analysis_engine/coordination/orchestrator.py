"""
Orchestration seam — selects and dispatches workflow runs.

Routes between the base analysis, AI narration, and layered meaning workflows
based on input flags. This is a Coordination Layer concern: it owns only the
routing decision and the result envelope. No domain logic lives here.
"""
from __future__ import annotations

from reveng.coordination.host_composition import build_default_host
from reveng.coordination.result_contract import make_error, make_ok
from reveng.storage.framework_logs import build_framework_log_sink
from reveng.analysis_engine.workflows.layered_breakdown import WORKFLOW_ID as LAYERED_WORKFLOW_ID
from reveng.analysis_engine.workflows.repo_analysis import WORKFLOW_ID, WORKFLOW_WITH_AI_ID

AGENT_ID = "OrchestratorAgent"


def run(inputs: dict, output_dir: str, run_id: str, *, provider=None, permission_check=None) -> dict:
    try:
        resolved_provider = provider
        if resolved_provider is None and (inputs.get("with_ai") or inputs.get("layered")):
            try:
                from reveng.integration.providers.factory import client_from_env
                resolved_provider = client_from_env(env_file=inputs.get("env_file", ".env"))
            except RuntimeError:
                resolved_provider = None

        workflow_id = (
            LAYERED_WORKFLOW_ID if inputs.get("layered")
            else WORKFLOW_WITH_AI_ID if inputs.get("with_ai")
            else WORKFLOW_ID
        )
        framework_log_sink = build_framework_log_sink()
        host = build_default_host(
            provider=resolved_provider,
            framework_log_sink=framework_log_sink,
            bootstrap_trigger="coordination.orchestrator.run",
            bootstrap_metadata={
                "run_id": run_id,
                "workflow_id": workflow_id,
                "with_ai": bool(inputs.get("with_ai")),
                "layered": bool(inputs.get("layered")),
            },
            run_id=run_id,
            workflow_id=workflow_id,
        )
        result = host.run_workflow(
            workflow_id,
            inputs=inputs,
            output_dir=output_dir,
            run_id=run_id,
            permission_check=permission_check,
        )
        return make_ok(
            AGENT_ID,
            run_id,
            outputs=result.outputs,
            upstream=result.upstream_paths,
            written=result.written_paths,
        )
    except Exception as exc:
        return make_error(
            AGENT_ID,
            run_id,
            f"{type(exc).__name__}: {exc}",
            upstream=[],
        )
