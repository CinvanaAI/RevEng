"""
/api/runs — trigger analysis runs, query status, events, and outputs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from reveng.platform.services.agent_service import AgentInactiveError, AgentNotFoundError, AgentService
from reveng.platform.services.agent_capability_access_service import (
    AgentCapabilityAccessService,
)
from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.analysis_bridge import submit_analysis_run
from reveng.platform.services.event_service import EventService
from reveng.platform.services.output_service import OutputService
from reveng.platform.services.provider_service import ProviderService
from reveng.platform.services.run_service import RunNotFoundError, RunService
from reveng.platform.web.deps import (
    get_agent_service,
    get_agent_capability_access_service,
    get_agent_keycard_service,
    get_event_service,
    get_output_service,
    get_provider_service,
    get_run_service,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TriggerRun(BaseModel):
    repo_path: str
    output_dir: str | None = None
    with_ai: bool = False
    layered: bool = False
    ai_limit: int | None = None
    extractor_workers: int = 6
    ai_file_workers: int = 10
    env_file: str = ".env"
    agent_id: str | None = None


def _run_dict(record) -> dict:
    return {
        "id": record.id,
        "status": record.status,
        "repo_path": record.repo_path,
        "output_dir": record.output_dir,
        "options": record.options,
        "agent_id": record.agent_id,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "error_message": record.error_message,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_runs(
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
    run_svc: RunService = Depends(get_run_service),
):
    offset = (page - 1) * per_page
    runs = run_svc.list_runs(limit=per_page, offset=offset, status=status)
    total = run_svc.count(status=status)
    return {
        "runs": [_run_dict(r) for r in runs],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("", status_code=202)
def trigger_run(
    body: TriggerRun,
    request: Request,
    run_svc: RunService = Depends(get_run_service),
    event_svc: EventService = Depends(get_event_service),
    output_svc: OutputService = Depends(get_output_service),
    agent_svc: AgentService = Depends(get_agent_service),
    agent_access_svc: AgentCapabilityAccessService = Depends(get_agent_capability_access_service),
    agent_keycard_svc: AgentKeycardService = Depends(get_agent_keycard_service),
    provider_svc: ProviderService = Depends(get_provider_service),
):
    try:
        run_id = submit_analysis_run(
            executor=request.app.state.executor,
            repo_path=body.repo_path,
            output_dir=body.output_dir,
            with_ai=body.with_ai,
            layered=body.layered,
            ai_limit=body.ai_limit,
            extractor_workers=body.extractor_workers,
            ai_file_workers=body.ai_file_workers,
            env_file=body.env_file,
            run_service=run_svc,
            event_service=event_svc,
            output_service=output_svc,
            agent_service=agent_svc,
            agent_capability_access_service=agent_access_svc,
            agent_keycard_service=agent_keycard_svc,
            provider_service=provider_svc,
            agent_id=body.agent_id,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {body.agent_id}")
    except AgentInactiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"run_id": run_id, "status": "pending"}


@router.get("/{run_id}")
def get_run(run_id: str, run_svc: RunService = Depends(get_run_service)):
    try:
        return _run_dict(run_svc.get_or_raise(run_id))
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")


@router.get("/{run_id}/events")
def get_run_events(
    run_id: str,
    since: str | None = None,
    event_svc: EventService = Depends(get_event_service),
    run_svc: RunService = Depends(get_run_service),
):
    try:
        run_svc.get_or_raise(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    events = event_svc.get_events_for_run(run_id, since=since)
    return {
        "run_id": run_id,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "run_type": e.run_type,
                "payload": e.payload,
                "created_at": e.created_at,
            }
            for e in events
        ],
    }


@router.get("/{run_id}/outputs")
def get_run_outputs(
    run_id: str,
    output_svc: OutputService = Depends(get_output_service),
    run_svc: RunService = Depends(get_run_service),
):
    try:
        run_svc.get_or_raise(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    outputs = output_svc.get_outputs_for_run(run_id)
    return {
        "run_id": run_id,
        "outputs": [
            {
                "id": o.id,
                "output_key": o.output_key,
                "output_type": o.output_type,
                "value": o.value,
                "metadata": o.metadata,
                "created_at": o.created_at,
            }
            for o in outputs
        ],
    }
