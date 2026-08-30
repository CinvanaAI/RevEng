"""
Analysis bridge — the single seam between the platform and the existing pipeline.

This is the platform seam that hands runs to the canonical orchestrator.
If the orchestrator API changes, only this file needs updating.

execute_analysis_run() is called in a background thread by the web layer.
It captures all status transitions, events, and output artifacts into the DB.
When a run is associated to an agent, it also keeps the agent's lightweight
current_run pointer in sync for the duration of the run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from reveng.coordination.result_contract import new_run_id
from reveng.framework.env import load_env_file
from reveng.integration.providers.factory import build_provider_client, build_provider_client_for_agent
from reveng.platform.services.agent_capability_access_service import (
    AgentCapabilityAccessService,
)
from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.agent_service import AgentService
from reveng.platform.services.event_service import EventService
from reveng.platform.services.output_service import OutputService
from reveng.platform.services.provider_service import ProviderService
from reveng.platform.services.run_service import RunService


def execute_analysis_run(
    run_id: str,
    inputs: dict,
    output_dir: str,
    *,
    run_service: RunService,
    event_service: EventService,
    output_service: OutputService,
    agent_service: AgentService | None = None,
    agent_capability_access_service: AgentCapabilityAccessService | None = None,
    agent_keycard_service: AgentKeycardService | None = None,
    provider: Any | None = None,
) -> None:
    """
    Execute a RevEng analysis run and capture everything into the DB.

    Called in a background thread.  Does not raise — all exceptions are
    caught and stored as failure state so the web layer can surface them.

    Parameters
    ----------
    run_id:
        The UUID that identifies this run.  It is the same value used in
        analysis_runs.id and passed to orchestrator.run(run_id=...) so that
        the DB record and the output directory are linked without any mapping.
    inputs:
        The inputs dict accepted by orchestrator.run().  At minimum:
        {"repo_path": str, "with_ai": bool, "layered": bool, ...}
    output_dir:
        Filesystem path for analysis output files.
    """
    event_service.append(run_id, "status_change", {"old": "pending", "new": "running"})
    run_service.mark_running(run_id)
    run_record = run_service.get_or_raise(run_id)
    agent_id = run_record.agent_id
    _set_agent_current_run(run_id, agent_id, agent_service, event_service)
    permission_check = (
        agent_capability_access_service.build_runtime_permission_check(agent_id)
        if agent_id and agent_capability_access_service is not None
        else None
    )

    try:
        from reveng.analysis_engine.coordination.orchestrator import run as orchestrator_run

        result = orchestrator_run(
            inputs=inputs,
            output_dir=output_dir,
            run_id=run_id,
            provider=provider,
            permission_check=permission_check,
        )
    except Exception as exc:
        _clear_agent_current_run(run_id, agent_id, agent_service, event_service)
        _fail(run_id, f"{type(exc).__name__}: {exc}", run_service, event_service)
        return

    if result.get("status") == "error":
        _clear_agent_current_run(run_id, agent_id, agent_service, event_service)
        _fail(run_id, result.get("error", "Unknown error"), run_service, event_service)
        return

    # Capture all output keys as run_output rows
    outputs: dict = result.get("outputs", {})
    for key, value in outputs.items():
        if isinstance(value, int):
            output_type = "count"
        elif isinstance(value, float):
            output_type = "count"
        else:
            output_type = "file_path"

        output_service.record(run_id, key, output_type, str(value))

        if output_type == "file_path" and value:
            event_service.append(run_id, "output_ready", {"key": key, "path": str(value)})

    run_service.mark_completed(run_id)
    _clear_agent_current_run(run_id, agent_id, agent_service, event_service)
    event_service.append(run_id, "status_change", {"old": "running", "new": "completed"})

    from reveng.desktop import notifications as _notifications
    _notifications.send("RevEng", f"Analysis complete: {inputs.get('repo_path', '')}")


def submit_analysis_run(
    *,
    executor: Any,
    repo_path: str,
    output_dir: str | None,
    with_ai: bool,
    layered: bool,
    ai_limit: int | None,
    extractor_workers: int,
    ai_file_workers: int,
    env_file: str,
    run_service: RunService,
    event_service: EventService,
    output_service: OutputService,
    agent_service: AgentService | None = None,
    agent_capability_access_service: AgentCapabilityAccessService | None = None,
    agent_keycard_service: AgentKeycardService | None = None,
    provider_service: ProviderService | None = None,
    agent_id: str | None = None,
) -> str:
    """
    Create a run record and hand it off to the background executor.

    This is the canonical platform-side submission seam used by both the API
    router and the HTML page route so run creation logic has a single owner.
    """
    if agent_id:
        if agent_service is None:
            raise RuntimeError("agent_service is required when agent_id is provided")
        if agent_capability_access_service is None:
            raise RuntimeError(
                "agent_capability_access_service is required when agent_id is provided"
            )
        if agent_keycard_service is None:
            raise RuntimeError(
                "agent_keycard_service is required when agent_id is provided"
            )
        agent_service.get_active_or_raise(agent_id)

    resolved_repo = str(Path(repo_path).expanduser().resolve())
    resolved_out = (
        str(Path(output_dir).expanduser().resolve())
        if output_dir and output_dir.strip()
        else str(Path(resolved_repo) / "output")
    )

    provider = _resolve_provider_for_run(
        with_ai=with_ai,
        layered=layered,
        env_file=env_file,
        provider_service=provider_service,
        agent_service=agent_service,
        agent_id=agent_id,
    )
    provider_id = getattr(provider, "provider_id", None)
    provider_model = getattr(provider, "model", None)

    run_id = new_run_id()
    options = {
        "with_ai": with_ai,
        "layered": layered,
        "ai_limit": ai_limit,
        "extractor_workers": extractor_workers,
        "ai_file_workers": ai_file_workers,
        "env_file": env_file,
    }
    if provider_id:
        options["provider_id"] = provider_id
    if provider_model:
        options["provider_model"] = provider_model
    run_service.create(
        run_id=run_id,
        repo_path=resolved_repo,
        output_dir=resolved_out,
        options=options,
        agent_id=agent_id,
    )
    event_service.append(run_id, "info", {"message": f"Run created for: {resolved_repo}"})

    orchestrator_inputs = {
        "repo_path": resolved_repo,
        "with_ai": with_ai,
        "layered": layered,
        "ai_limit": ai_limit,
        "extractor_workers": extractor_workers,
        "ai_file_workers": ai_file_workers,
        "env_file": env_file,
    }
    if agent_id:
        orchestrator_inputs["agent_keycard_visibility"] = (
            agent_keycard_service.build_run_visibility_context(agent_id, resolved_repo)
        )
    executor.submit(
        execute_analysis_run,
        run_id,
        orchestrator_inputs,
        resolved_out,
        run_service=run_service,
        event_service=event_service,
        output_service=output_service,
        agent_service=agent_service,
        agent_capability_access_service=agent_capability_access_service,
        agent_keycard_service=agent_keycard_service,
        provider=provider,
    )
    return run_id


def _fail(
    run_id: str,
    error: str,
    run_service: RunService,
    event_service: EventService,
) -> None:
    run_service.mark_failed(run_id, error)
    event_service.append(run_id, "status_change", {"old": "running", "new": "failed"})
    event_service.append(run_id, "error", {"message": error})


def _set_agent_current_run(
    run_id: str,
    agent_id: str | None,
    agent_service: AgentService | None,
    event_service: EventService,
) -> None:
    if not agent_id or agent_service is None:
        return
    try:
        agent_service.set_current_run(agent_id, run_id)
    except Exception as exc:
        event_service.append(
            run_id,
            "warning",
            {"message": f"Could not set agent current_run_id: {type(exc).__name__}: {exc}"},
        )


def _clear_agent_current_run(
    run_id: str,
    agent_id: str | None,
    agent_service: AgentService | None,
    event_service: EventService,
) -> None:
    if not agent_id or agent_service is None:
        return
    try:
        agent_service.set_current_run(agent_id, None)
    except Exception as exc:
        event_service.append(
            run_id,
            "warning",
            {"message": f"Could not clear agent current_run_id: {type(exc).__name__}: {exc}"},
        )


def _resolve_provider_for_run(
    *,
    with_ai: bool,
    layered: bool,
    env_file: str,
    provider_service: ProviderService | None,
    agent_service: AgentService | None,
    agent_id: str | None,
) -> Any | None:
    if not (with_ai or layered):
        return None
    if provider_service is None:
        return None

    env_values = load_env_file(env_file)

    if agent_id:
        if agent_service is None:
            raise RuntimeError("agent_service is required when agent_id is provided")
        spec = agent_service.get_spec(agent_id)
        provider_record = provider_service.get(spec.tool_access.provider_id)
        if provider_record is None:
            raise RuntimeError(
                f"Agent references unknown provider '{spec.tool_access.provider_id}'"
            )
        return build_provider_client_for_agent(
            provider_record,
            spec.tool_access.model,
            env_values,
        )

    provider_record = provider_service.get_default()
    if provider_record is None:
        raise RuntimeError(
            "No provider records are configured for AI-enabled platform runs."
        )
    return build_provider_client(provider_record, env_values)