"""
UI page routes — Jinja2 template rendering for the control center.

Each route renders a full HTML page.  HTMX targets embedded within those
pages call the /api/* routes directly; the page routes here only serve
the initial full-page loads and form submissions that require a redirect.

Note: uses Starlette 1.0+ TemplateResponse signature:
    templates.TemplateResponse(request, "name.html", context={...})
  NOT the old Starlette <0.28 signature:
    templates.TemplateResponse("name.html", {"request": request, ...})
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from reveng.execution_environment.agent_environment import (
    DEFAULT_AGENT_ENVIRONMENT_SKIN_ID,
    AgentEnvironmentAppearanceService,
    AgentEnvironmentService,
)
from reveng.execution_environment.capability_environment import (
    CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID,
    CapabilityEnvironmentService,
    resolve_capability_environment_station_action,
)
from reveng.storage.db_connection import get_db
from reveng.platform.models.capability_draft import CapabilityDraftNotFoundError
from reveng.platform.services.agent_keycard_service import AgentKeycardService
from reveng.platform.services.agent_service import AgentNotFoundError, AgentService
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
from reveng.platform.services.agent_workflow_service import AgentWorkflowService
from reveng.platform.services.analysis_bridge import submit_analysis_run
from reveng.platform.services.capability_catalog_service import (
    CapabilityCatalogService,
    CapabilityRecordNotFoundError,
)
from reveng.platform.services.draft_service import CapabilityDraftService
from reveng.platform.services.event_service import EventService
from reveng.platform.services.output_service import OutputService
from reveng.platform.services.provider_service import ProviderService
from reveng.platform.services.run_service import RunNotFoundError, RunService
from reveng.platform.services.capability_package_service import CapabilityPackageService
from reveng.platform.web.deps import (
    get_agent_keycard_service,
    get_agent_service,
    get_agent_tool_file_permission_service,
    get_agent_workflow_service,
    get_agent_environment_service,
    get_agent_environment_appearance_service,
    get_capability_catalog_service,
    get_capability_environment_service,
    get_capability_draft_service,
    get_capability_package_service,
    get_event_service,
    get_output_service,
    get_provider_service,
    get_run_service,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()

_CAP_ENV_STATIONS = {
    "create_draft",
    "inventory_wall",
    "workbench",
    "ledger",
    "dispatch_bench",
    "draft",
}


# ---------------------------------------------------------------------------
# Flash state  (single-user, single-process — safe for desktop app)
# ---------------------------------------------------------------------------

_flash_state: dict[str, str | None] = {"notice": None, "error": None}


def _set_flash(*, notice: str | None = None, error: str | None = None) -> None:
    _flash_state["notice"] = notice
    _flash_state["error"] = error


def _consume_flash() -> dict[str, str | None]:
    data = {"page_notice": _flash_state["notice"], "page_error": _flash_state["error"]}
    _flash_state["notice"] = None
    _flash_state["error"] = None
    return data


# ---------------------------------------------------------------------------
# Station helpers
# ---------------------------------------------------------------------------

def _resolve_cap_env_station(request: Request, *, default: str) -> str:
    station = resolve_capability_environment_station_action(
        request.query_params.get("station")
    )
    if station in _CAP_ENV_STATIONS:
        return station
    return default


# ---------------------------------------------------------------------------
# URL path builders (no return_to, no flash in URLs)
# ---------------------------------------------------------------------------

def _capabilities_entry_path() -> str:
    return "/capabilities"


def _capabilities_professional_path() -> str:
    return "/capabilities"


def _agent_environment_entry_path(*, agent_id: str | None = None) -> str:
    if agent_id:
        return f"/agent-environment?agent={quote(agent_id)}"
    return "/agent-environment"


def _agent_environment_agent_path(
    agent_id: str,
    *,
    station: str | None = None,
) -> str:
    path = f"/agent-environment/agents/{agent_id}"
    if station == "tools_station":
        return f"{path}/tools"
    if station == "keycard_station":
        return f"{path}/keycard"
    return path


def _capabilities_settings_path() -> str:
    return "/capabilities/settings"


def _agents_environment_settings_path() -> str:
    return "/agents/environment-settings"


def _capability_environment_entry_path() -> str:
    return "/capability-environment"


def _capability_environment_skin_path(
    skin_id: str,
    *,
    station: str | None = None,
    draft_id: str | None = None,
    package_id: str | None = None,
) -> str:
    params: list[str] = []
    if station:
        params.append(f"station={quote(station)}")
    if draft_id:
        params.append(f"draft={quote(draft_id)}")
    if package_id:
        params.append(f"package={quote(package_id, safe='')}")
    if not params:
        return f"/capability-environment/skins/{skin_id}"
    return f"/capability-environment/skins/{skin_id}?{'&'.join(params)}"


def _capability_environment_scene_path(
    base_path: str,
    *,
    station: str | None = None,
    draft_id: str | None = None,
) -> str:
    params: list[str] = []
    if station:
        params.append(f"station={quote(station)}")
    if draft_id:
        params.append(f"draft={quote(draft_id)}")
    if not params:
        return base_path
    return f"{base_path}?{'&'.join(params)}"


def _capability_platform_draft_path(draft_id: str) -> str:
    return f"/capabilities/drafts/{draft_id}"


def _capability_platform_live_path(capability_id: str) -> str:
    return f"/capabilities/live/{capability_id}"


def _capability_package_page_path(capability_id: str) -> str:
    return f"/capabilities/{capability_id}/package"


def _capability_environment_package_path(
    capability_id: str,
    *,
    station: str = "pkg_live",
) -> str:
    return f"/capability-environment?package={quote(capability_id, safe='')}&station={station}"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _pretty_json(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _parse_object_json(raw: str, *, field_name: str) -> dict[str, object]:
    payload = raw.strip()
    if not payload:
        return {}
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc.msg}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must decode to a JSON object.")
    return decoded


# ---------------------------------------------------------------------------
# Manifestation context helpers
# ---------------------------------------------------------------------------

def _cap_env_manifestation_context(
    *,
    env_svc: CapabilityEnvironmentService,
) -> dict[str, object]:
    settings = env_svc.get_settings()
    return {
        "capability_environment_settings": settings,
        "capability_environment_root_href": _capability_environment_entry_path(),
        "capability_environment_professional_href": _capabilities_entry_path(),
        "capability_environment_settings_href": _capabilities_settings_path(),
        "capability_environment_entry_mode": "skins" if settings.enable_skins else "neutral",
    }


def _render_capability_environment_place(
    *,
    request: Request,
    env_svc: CapabilityEnvironmentService,
    selected_skin,
    base_path: str,
    active_station: str | None,
    selected_draft_id: str | None,
):
    context = env_svc.build_place_context(
        base_path=base_path,
        active_station=active_station,
        selected_draft_id=selected_draft_id,
        return_to="/capabilities",
        return_label="Capabilities",
        return_to_query="",
        recent_draft_ids=[],
    )
    return templates.TemplateResponse(
        request,
        "capability_environment/place.html",
        context={
            "active_nav": "capability-environment",
            **_cap_env_manifestation_context(env_svc=env_svc),
            **context,
            "active_station": active_station,
            "skin": selected_skin,
            "return_to": "/capabilities",
            "return_label": "Capabilities",
            "return_to_query": "",
            "action_links": env_svc.build_skin_action_links(
                base_path=base_path,
                return_to_query="",
                return_to="/capabilities",
            ),
            **_consume_flash(),
        },
    )


def _render_missing_environment_skin(
    *,
    request: Request,
    env_svc: CapabilityEnvironmentService,
    skin_id: str,
):
    return templates.TemplateResponse(
        request,
        "capability_environment/skin_not_found.html",
        context={
            "active_nav": "capability-environment",
            **_cap_env_manifestation_context(env_svc=env_svc),
            **env_svc.build_place_context(
                base_path="/capability-environment",
                active_station=None,
                selected_draft_id=None,
                return_to="/capabilities",
                return_label="Capabilities",
                return_to_query="",
                recent_draft_ids=[],
            ),
            "return_to": "/capabilities",
            "return_label": "Capabilities",
            "return_to_query": "",
            "missing_skin_id": skin_id,
            **_consume_flash(),
        },
        status_code=404,
    )


def _build_capability_platform_workspace_context(
    *,
    request: Request,
    draft_svc: CapabilityDraftService,
    catalog_svc: CapabilityCatalogService,
) -> dict[str, object]:
    drafts = draft_svc.list_drafts()
    installed = catalog_svc.list_installed_inventory_entries()
    publication_records: list[dict[str, object]] = []
    publication_candidate_count = 0
    draft_rows: list[dict[str, object]] = []

    for draft in drafts:
        items = draft_svc.list_draft_items(draft.id)
        revisions = draft_svc.get_draft_revision_history(draft.id)
        history = draft_svc.get_draft_publication_history(draft.id)
        candidates = draft_svc.get_draft_publication_candidates(draft.id)
        publication_candidate_count += len(candidates)
        draft_rows.append(
            {
                "draft": draft,
                "item_count": len(items),
                "validated_count": sum(1 for item in items if item.item_state == "validated"),
                "published_count": sum(1 for item in items if item.item_state == "published"),
                "revision_count": len(revisions),
                "publication_count": len(history),
                "href": _capability_platform_draft_path(draft.id),
            }
        )
        for record in history:
            publication_records.append(
                {
                    "draft": draft,
                    "record": record,
                    "href": _capability_platform_draft_path(draft.id) + "#ledger-history",
                }
            )

    publication_records.sort(
        key=lambda entry: (str(entry["record"].published_at), str(entry["draft"].id)),
        reverse=True,
    )

    live_rows = [
        {
            "capability": capability,
            "href": _capability_platform_live_path(capability["capability_id"]),
            "package_href": _capability_package_page_path(capability["capability_id"]),
        }
        for capability in installed
    ]

    return {
        "active_nav": "capabilities",
        "return_to": "/capabilities",
        "return_label": "Capabilities",
        "return_to_query": "",
        "workspace_stats": {
            "draft_count": len(drafts),
            "active_draft_count": sum(
                1 for draft in drafts if draft.lifecycle_state == "draft"
            ),
            "published_draft_count": sum(
                1 for draft in drafts if draft.lifecycle_state == "published"
            ),
            "installed_count": len(installed),
            "publication_record_count": len(publication_records),
            "publication_candidate_count": publication_candidate_count,
            "package_object_count": sum(
                1 for capability in installed if capability.get("package_object_id")
            ),
        },
        "draft_rows": draft_rows,
        "live_rows": live_rows,
        "publication_rows": publication_records[:12],
        "platform_limitations": [
            {
                "title": "Live uninstall or deprecate",
                "detail": (
                    "Capability Platform currently installs and replaces live truth through "
                    "draft publication, but it does not yet expose a lawful live uninstall or "
                    "deprecate path."
                ),
            },
            {
                "title": "Stored diff / compare",
                "detail": (
                    "Draft versions, publication history, and package snapshots are stored, but "
                    "there is no dedicated diff surface yet."
                ),
            },
        ],
        **_consume_flash(),
    }


def _build_capability_platform_draft_context(
    *,
    request: Request,
    draft_svc: CapabilityDraftService,
    draft_id: str,
) -> dict[str, object]:
    spec = draft_svc.get_draft_spec(draft_id)
    revisions = draft_svc.get_draft_revision_history(draft_id)
    history = draft_svc.get_draft_publication_history(draft_id)
    candidates = draft_svc.get_draft_publication_candidates(draft_id)
    export_snippet = draft_svc.export_draft_as_pack_snippet(draft_id)
    items = [
        {
            "item": item,
            "draft_data_json": _pretty_json(item.draft_data),
            "rollback_source_kind": item.draft_data.get("rollback_source_kind"),
            "rollback_source_id": item.draft_data.get("rollback_source_id"),
            "rollback_source_version": item.draft_data.get("rollback_source_version"),
        }
        for item in spec.items
    ]
    return {
        "active_nav": "capabilities",
        "return_to": "/capabilities",
        "return_label": "Capabilities",
        "return_to_query": "",
        "workspace_href": _capabilities_entry_path(),
        "draft": spec.draft,
        "draft_spec": spec,
        "draft_items": items,
        "draft_item_counts": {
            "total": len(spec.items),
            "draft": sum(1 for item in spec.items if item.item_state == "draft"),
            "validated": sum(1 for item in spec.items if item.item_state == "validated"),
            "published": sum(1 for item in spec.items if item.item_state == "published"),
        },
        "revision_records": revisions,
        "publication_records": history,
        "publication_candidates": candidates,
        "export_snippet": export_snippet,
        "new_item_template_json": _pretty_json(
            {
                "capability_id": "",
                "display_name": "",
                "description": "",
                "capability_type": "function",
                "pack_id": "",
                "version": spec.draft.version,
                "contract": {
                    "inputs": [],
                    "output": [],
                    "constraints": [],
                },
                "implementation_ref": "",
                "tags": [],
            }
        ),
        "platform_limitations": [
            "Direct live edit is intentionally unavailable. Drafts remain the lawful edit path.",
            "There is no dedicated compare/diff surface yet for revision or publication snapshots.",
        ],
        **_consume_flash(),
    }


def _build_capability_package_page_context(
    *,
    request: Request,
    package_svc: CapabilityPackageService,
    capability_id: str,
) -> dict[str, object]:
    pkg = package_svc.get_package(capability_id)
    return {
        "active_nav": "capabilities",
        "return_to": "/capabilities",
        "return_label": "Capabilities",
        "return_to_query": "",
        "workspace_href": _capabilities_entry_path(),
        "package_page_href": _capability_package_page_path(capability_id),
        "pkg": pkg,
        "published": pkg.published,
        "unpublished": pkg.unpublished,
        "history": pkg.history,
        "live": pkg.published,
        "draft": pkg.unpublished,
        **_consume_flash(),
    }


# ---------------------------------------------------------------------------
# Agent Environment
# ---------------------------------------------------------------------------

@router.get("/agent-environment", response_class=HTMLResponse, include_in_schema=False)
def agent_environment_entry(
    request: Request,
    env_svc: AgentEnvironmentService = Depends(get_agent_environment_service),
):
    selected_agent_id = request.query_params.get("agent", "").strip() or None
    canonical_agent_id = env_svc.resolve_hall_agent_id(selected_agent_id)
    if canonical_agent_id and canonical_agent_id != selected_agent_id:
        return RedirectResponse(
            url=_agent_environment_entry_path(agent_id=canonical_agent_id),
            status_code=303,
        )
    return templates.TemplateResponse(
        request,
        "agent_environment/hall.html",
        context={
            "active_nav": "agent-environment",
            **env_svc.build_hall_context(
                selected_agent_id=canonical_agent_id,
                return_to="/agents",
                return_label="Control Center",
                return_to_query="",
            ),
            **_consume_flash(),
        },
    )


@router.get(
    "/agent-environment/agents/{agent_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def agent_environment_agent_bay(
    agent_id: str,
    request: Request,
    env_svc: AgentEnvironmentService = Depends(get_agent_environment_service),
):
    try:
        context = env_svc.build_agent_bay_context(
            selected_agent_id=agent_id,
            active_station=None,
            explorer_root_path=request.query_params.get("root", "").strip() or None,
            explorer_current_path=request.query_params.get("browse", "").strip() or None,
            return_to="/agent-environment",
            return_label="Agent Environment",
            return_to_query="",
        )
    except AgentNotFoundError:
        return RedirectResponse(url=_agent_environment_entry_path(), status_code=303)
    return templates.TemplateResponse(
        request,
        "agent_environment/bay.html",
        context={"active_nav": "agent-environment", **context, **_consume_flash()},
    )


@router.get(
    "/agent-environment/agents/{agent_id}/tools",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def agent_environment_tools_station(
    agent_id: str,
    request: Request,
    env_svc: AgentEnvironmentService = Depends(get_agent_environment_service),
):
    try:
        context = env_svc.build_agent_bay_context(
            selected_agent_id=agent_id,
            active_station="tools_station",
            explorer_root_path=request.query_params.get("root", "").strip() or None,
            explorer_current_path=request.query_params.get("browse", "").strip() or None,
            return_to="/agent-environment",
            return_label="Agent Environment",
            return_to_query="",
        )
    except AgentNotFoundError:
        return RedirectResponse(url=_agent_environment_entry_path(), status_code=303)
    return templates.TemplateResponse(
        request,
        "agent_environment/bay.html",
        context={"active_nav": "agent-environment", **context, **_consume_flash()},
    )


@router.get(
    "/agent-environment/agents/{agent_id}/keycard",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def agent_environment_keycard_station(
    agent_id: str,
    request: Request,
    env_svc: AgentEnvironmentService = Depends(get_agent_environment_service),
):
    try:
        context = env_svc.build_agent_bay_context(
            selected_agent_id=agent_id,
            active_station="keycard_station",
            explorer_root_path=request.query_params.get("root", "").strip() or None,
            explorer_current_path=request.query_params.get("browse", "").strip() or None,
            return_to="/agent-environment",
            return_label="Agent Environment",
            return_to_query="",
        )
    except AgentNotFoundError:
        return RedirectResponse(url=_agent_environment_entry_path(), status_code=303)
    return templates.TemplateResponse(
        request,
        "agent_environment/bay.html",
        context={"active_nav": "agent-environment", **context, **_consume_flash()},
    )


@router.post(
    "/agent-environment/agents/{agent_id}/appearance/random",
    include_in_schema=False,
)
def agent_environment_set_random_background(
    agent_id: str,
    request: Request,
    appearance_svc: AgentEnvironmentAppearanceService = Depends(
        get_agent_environment_appearance_service
    ),
):
    try:
        appearance_svc.set_random_background(agent_id, DEFAULT_AGENT_ENVIRONMENT_SKIN_ID)
        _set_flash(notice="Front-hall background reset to Default / Random.")
    except AgentNotFoundError:
        return RedirectResponse(url=_agent_environment_entry_path(), status_code=303)
    except ValueError as exc:
        _set_flash(error=str(exc))
    return RedirectResponse(url=_agent_environment_agent_path(agent_id), status_code=303)


@router.post(
    "/agent-environment/agents/{agent_id}/appearance/shared",
    include_in_schema=False,
)
def agent_environment_set_shared_background(
    agent_id: str,
    request: Request,
    asset_id: str = Form(...),
    appearance_svc: AgentEnvironmentAppearanceService = Depends(
        get_agent_environment_appearance_service
    ),
):
    try:
        appearance_svc.set_shared_background(
            agent_id,
            DEFAULT_AGENT_ENVIRONMENT_SKIN_ID,
            asset_id.strip(),
        )
        _set_flash(notice="Shared Skynet background selected for this agent.")
    except AgentNotFoundError:
        return RedirectResponse(url=_agent_environment_entry_path(), status_code=303)
    except (KeyError, ValueError) as exc:
        _set_flash(error=str(exc))
    return RedirectResponse(url=_agent_environment_agent_path(agent_id), status_code=303)


@router.post(
    "/agent-environment/agents/{agent_id}/appearance/custom/select",
    include_in_schema=False,
)
def agent_environment_set_custom_background(
    agent_id: str,
    request: Request,
    asset_id: str = Form(...),
    appearance_svc: AgentEnvironmentAppearanceService = Depends(
        get_agent_environment_appearance_service
    ),
):
    try:
        appearance_svc.set_custom_background(
            agent_id,
            DEFAULT_AGENT_ENVIRONMENT_SKIN_ID,
            asset_id.strip(),
        )
        _set_flash(notice="Custom background selected for this agent.")
    except AgentNotFoundError:
        return RedirectResponse(url=_agent_environment_entry_path(), status_code=303)
    except (KeyError, ValueError) as exc:
        _set_flash(error=str(exc))
    return RedirectResponse(url=_agent_environment_agent_path(agent_id), status_code=303)


@router.post(
    "/agent-environment/agents/{agent_id}/appearance/custom/upload",
    include_in_schema=False,
)
async def agent_environment_upload_custom_background(
    agent_id: str,
    request: Request,
    background_file: UploadFile = File(...),
    appearance_svc: AgentEnvironmentAppearanceService = Depends(
        get_agent_environment_appearance_service
    ),
):
    try:
        filename = (background_file.filename or "").strip()
        if not filename:
            raise ValueError("Choose an image file to upload.")
        appearance_svc.store_custom_background(
            agent_id,
            DEFAULT_AGENT_ENVIRONMENT_SKIN_ID,
            filename=filename,
            content=await background_file.read(),
        )
        _set_flash(notice="Custom background uploaded and selected for this agent.")
    except AgentNotFoundError:
        return RedirectResponse(url=_agent_environment_entry_path(), status_code=303)
    except ValueError as exc:
        _set_flash(error=str(exc))
    return RedirectResponse(url=_agent_environment_agent_path(agent_id), status_code=303)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@router.get("/agents", response_class=HTMLResponse, include_in_schema=False)
def agents_list(
    request: Request,
    svc: AgentService = Depends(get_agent_service),
    provider_svc: ProviderService = Depends(get_provider_service),
):
    agents = svc.list_all()
    providers = {p.id: p for p in provider_svc.list_all()}
    agent_rows = [
        {
            "agent": agent,
            "tool_ids": svc.get_spec(agent.id).tool_access.allowed_capability_ids,
        }
        for agent in agents
    ]
    return templates.TemplateResponse(
        request,
        "agents/list.html",
        context={
            "agent_rows": agent_rows,
            "providers": providers,
            "agent_environment_settings_path": _agents_environment_settings_path(),
        },
    )


@router.get(
    "/agents/environment-settings",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def agent_environment_settings_page(
    request: Request,
    appearance_svc: AgentEnvironmentAppearanceService = Depends(
        get_agent_environment_appearance_service
    ),
):
    theme = appearance_svc.get_theme(DEFAULT_AGENT_ENVIRONMENT_SKIN_ID)
    shared_backgrounds = appearance_svc.list_shared_backgrounds(DEFAULT_AGENT_ENVIRONMENT_SKIN_ID)
    return templates.TemplateResponse(
        request,
        "agents/environment_settings.html",
        context={
            "active_nav": "agents",
            "return_to": "/agents",
            "return_label": "Agents",
            "return_to_query": "",
            "theme": theme,
            "shared_backgrounds": [
                {
                    "asset": asset,
                    "asset_url": appearance_svc.asset_url_for(asset.storage_path),
                }
                for asset in shared_backgrounds
            ],
            "agent_environment_entry_path": _agent_environment_entry_path(),
            **_consume_flash(),
        },
    )


@router.post(
    "/agents/environment-settings/shared-backgrounds",
    include_in_schema=False,
)
async def agent_environment_upload_shared_background(
    request: Request,
    background_file: UploadFile = File(...),
    appearance_svc: AgentEnvironmentAppearanceService = Depends(
        get_agent_environment_appearance_service
    ),
):
    try:
        filename = (background_file.filename or "").strip()
        if not filename:
            raise ValueError("Choose an image file to upload.")
        appearance_svc.store_shared_background(
            DEFAULT_AGENT_ENVIRONMENT_SKIN_ID,
            filename=filename,
            content=await background_file.read(),
        )
        _set_flash(notice="Shared Skynet background uploaded.")
    except ValueError as exc:
        _set_flash(error=str(exc))
    return RedirectResponse(url=_agents_environment_settings_path(), status_code=303)


@router.get("/agents/new", response_class=HTMLResponse, include_in_schema=False)
def agent_new_form(
    request: Request,
    provider_svc: ProviderService = Depends(get_provider_service),
):
    return templates.TemplateResponse(
        request,
        "agents/create.html",
        context={"providers": provider_svc.list_all()},
    )


@router.post("/agents/new", include_in_schema=False)
def agent_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    provider_id: str = Form(...),
    model: str = Form(...),
    system_prompt: str = Form(""),
    svc: AgentService = Depends(get_agent_service),
):
    svc.create(
        name=name,
        description=description,
        provider_id=provider_id,
        model=model,
        system_prompt=system_prompt,
    )
    return RedirectResponse(url="/agents", status_code=303)


@router.get("/agents/{agent_id}", response_class=HTMLResponse, include_in_schema=False)
def agent_detail(
    agent_id: str,
    request: Request,
    svc: AgentService = Depends(get_agent_service),
    workflow_svc: AgentWorkflowService = Depends(get_agent_workflow_service),
    provider_svc: ProviderService = Depends(get_provider_service),
    run_svc: RunService = Depends(get_run_service),
    keycard_svc: AgentKeycardService = Depends(get_agent_keycard_service),
    tool_file_perm_svc: AgentToolFilePermissionService = Depends(
        get_agent_tool_file_permission_service
    ),
):
    try:
        agent = svc.get_or_raise(agent_id)
    except AgentNotFoundError:
        return RedirectResponse(url="/agents")

    from reveng.platform.services.agent_workflow_bridge import preview_workflow_targets
    from reveng.agents.triggers import MANUAL, ALL_ACTIVATION_KINDS

    spec = svc.get_spec(agent_id)
    provider = provider_svc.get(spec.tool_access.provider_id)
    recent_runs = [r for r in run_svc.list_runs(limit=20) if r.agent_id == agent_id]
    workflow_runs = [r for r in recent_runs if r.options.get("workflow")]
    agent_workflows = workflow_svc.list_for_agent(agent_id)
    manual_ordered_workflows = workflow_svc.list_for_activation_trigger(agent_id, MANUAL)
    manual_run_order = workflow_svc.get_manual_run_order(agent_id)
    workflow_target_preview = preview_workflow_targets(
        agent_id,
        agent_workflow_service=workflow_svc,
        agent_keycard_service=keycard_svc,
        agent_tool_file_permission_service=tool_file_perm_svc,
    )

    return templates.TemplateResponse(
        request,
        "agents/detail.html",
        context={
            "agent": agent,
            "spec": spec,
            "provider": provider,
            "recent_runs": recent_runs,
            "workflow_runs": workflow_runs,
            "agent_workflows": agent_workflows,
            "manual_ordered_workflows": manual_ordered_workflows,
            "manual_run_order": manual_run_order,
            "all_activation_kinds": list(ALL_ACTIVATION_KINDS),
            "workflow_target_preview": workflow_target_preview,
            "agent_environment_path": _agent_environment_agent_path(agent_id),
        },
    )


@router.get("/agents/{agent_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def agent_edit_form(
    agent_id: str,
    request: Request,
    svc: AgentService = Depends(get_agent_service),
    provider_svc: ProviderService = Depends(get_provider_service),
):
    try:
        agent = svc.get_or_raise(agent_id)
    except AgentNotFoundError:
        return RedirectResponse(url="/agents")
    return templates.TemplateResponse(
        request,
        "agents/edit.html",
        context={"agent": agent, "providers": provider_svc.list_all()},
    )


@router.post("/agents/{agent_id}/edit", include_in_schema=False)
def agent_update(
    agent_id: str,
    name: str = Form(...),
    description: str = Form(""),
    provider_id: str = Form(...),
    model: str = Form(...),
    system_prompt: str = Form(""),
    svc: AgentService = Depends(get_agent_service),
):
    try:
        svc.update(
            agent_id,
            name=name,
            description=description,
            provider_id=provider_id,
            model=model,
            system_prompt=system_prompt,
        )
    except AgentNotFoundError:
        pass
    return RedirectResponse(url=f"/agents/{agent_id}", status_code=303)


@router.post("/agents/{agent_id}/delete", include_in_schema=False)
def agent_delete(agent_id: str, svc: AgentService = Depends(get_agent_service)):
    try:
        svc.delete(agent_id)
    except AgentNotFoundError:
        pass
    return RedirectResponse(url="/agents", status_code=303)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

@router.get("/runs", response_class=HTMLResponse, include_in_schema=False)
def runs_list(
    request: Request,
    page: int = 1,
    run_svc: RunService = Depends(get_run_service),
):
    per_page = 30
    runs = run_svc.list_runs(limit=per_page, offset=(page - 1) * per_page)
    total = run_svc.count()
    return templates.TemplateResponse(
        request,
        "runs/list.html",
        context={
            "runs": runs,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        },
    )


@router.get("/runs/new", response_class=HTMLResponse, include_in_schema=False)
def run_new_form(request: Request):
    return templates.TemplateResponse(request, "runs/trigger.html")


@router.post("/runs/new", include_in_schema=False)
def run_trigger(
    request: Request,
    repo_path: str = Form(...),
    output_dir: str = Form(""),
    with_ai: str | None = Form(None),
    layered: str | None = Form(None),
    ai_limit: str = Form(""),
    extractor_workers: int = Form(6),
    ai_file_workers: int = Form(8),
    env_file: str = Form(".env"),
    run_svc: RunService = Depends(get_run_service),
    event_svc: EventService = Depends(get_event_service),
    output_svc: OutputService = Depends(get_output_service),
    provider_svc: ProviderService = Depends(get_provider_service),
):
    ai_limit_val = int(ai_limit) if ai_limit.strip().isdigit() else None
    with_ai_bool = with_ai is not None and with_ai not in ("", "false", "0")
    layered_bool = layered is not None and layered not in ("", "false", "0")
    try:
        run_id = submit_analysis_run(
            executor=request.app.state.executor,
            repo_path=repo_path,
            output_dir=output_dir,
            with_ai=with_ai_bool,
            layered=layered_bool,
            ai_limit=ai_limit_val,
            extractor_workers=extractor_workers,
            ai_file_workers=ai_file_workers,
            env_file=env_file,
            run_service=run_svc,
            event_service=event_svc,
            output_service=output_svc,
            provider_service=provider_svc,
        )
    except RuntimeError:
        return RedirectResponse(url="/providers", status_code=303)

    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.get("/runs/{run_id}", response_class=HTMLResponse, include_in_schema=False)
def run_detail(
    run_id: str,
    request: Request,
    run_svc: RunService = Depends(get_run_service),
    event_svc: EventService = Depends(get_event_service),
    output_svc: OutputService = Depends(get_output_service),
):
    try:
        run = run_svc.get_or_raise(run_id)
    except RunNotFoundError:
        return RedirectResponse(url="/runs")

    events = event_svc.get_events_for_run(run_id)
    outputs = output_svc.get_outputs_for_run(run_id)
    return templates.TemplateResponse(
        request,
        "runs/detail.html",
        context={
            "run": run,
            "events": events,
            "outputs": outputs,
            "is_active": run.status in ("pending", "running"),
        },
    )


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

@router.get("/providers", response_class=HTMLResponse, include_in_schema=False)
def providers_list(
    request: Request,
    svc: ProviderService = Depends(get_provider_service),
):
    return templates.TemplateResponse(
        request,
        "providers/list.html",
        context={"providers": svc.list_all()},
    )


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

@router.get("/capabilities", response_class=HTMLResponse, include_in_schema=False)
def capabilities_entry(
    request: Request,
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
    catalog_svc: CapabilityCatalogService = Depends(get_capability_catalog_service),
):
    return templates.TemplateResponse(
        request,
        "capabilities/workspace.html",
        context=_build_capability_platform_workspace_context(
            request=request,
            draft_svc=draft_svc,
            catalog_svc=catalog_svc,
        ),
    )


@router.get(
    "/capabilities/professional",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capabilities_professional(request: Request):
    return RedirectResponse(url=_capabilities_entry_path(), status_code=303)


@router.get("/capabilities/settings", response_class=HTMLResponse, include_in_schema=False)
def capabilities_settings(
    request: Request,
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    context = env_svc.build_settings_surface_context(
        return_to="/capabilities",
        return_label="Capabilities",
        return_to_query="",
        recent_draft_ids=[],
    )
    return templates.TemplateResponse(
        request,
        "capabilities/settings.html",
        context={
            "active_nav": "capabilities-settings",
            **_cap_env_manifestation_context(env_svc=env_svc),
            **context,
        },
    )


@router.post("/capabilities/settings", include_in_schema=False)
def capabilities_settings_update(
    request: Request,
    enable_skins: str | None = Form(None),
    selected_skin_id: str = Form("random"),
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    env_svc.update_settings(
        enable_skins=enable_skins is not None and enable_skins not in ("", "false", "0"),
        selected_skin_id=selected_skin_id,
    )
    return RedirectResponse(url=_capabilities_settings_path(), status_code=303)


@router.post("/capabilities/drafts", include_in_schema=False)
def capability_platform_create_draft(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    version: str = Form("1.0.0"),
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    if not name.strip():
        _set_flash(error="Draft name is required.")
        return RedirectResponse(url="/capabilities", status_code=303)
    draft = draft_svc.create_draft(
        name=name.strip(),
        description=description.strip(),
        version=version.strip() or "1.0.0",
    )
    _set_flash(notice="Draft created.")
    return RedirectResponse(url=_capability_platform_draft_path(draft.id), status_code=303)


@router.get(
    "/capabilities/drafts/{draft_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capability_platform_draft_detail(
    draft_id: str,
    request: Request,
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        draft_svc.get_draft_or_raise(draft_id)
    except CapabilityDraftNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)

    return templates.TemplateResponse(
        request,
        "capabilities/draft_detail.html",
        context=_build_capability_platform_draft_context(
            request=request,
            draft_svc=draft_svc,
            draft_id=draft_id,
        ),
    )


@router.post("/capabilities/drafts/{draft_id}/edit", include_in_schema=False)
def capability_platform_update_draft(
    draft_id: str,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        if not name.strip():
            raise ValueError("Draft name is required.")
        draft_svc.update_draft(
            draft_id,
            name=name.strip(),
            description=description.strip(),
        )
        _set_flash(notice="Draft details saved.")
    except CapabilityDraftNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    except ValueError as exc:
        _set_flash(error=str(exc))
    return RedirectResponse(url=_capability_platform_draft_path(draft_id), status_code=303)


@router.post("/capabilities/drafts/{draft_id}/delete", include_in_schema=False)
def capability_platform_delete_draft(
    draft_id: str,
    request: Request,
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        draft_svc.delete_draft(draft_id)
    except CapabilityDraftNotFoundError:
        pass
    return RedirectResponse(url="/capabilities", status_code=303)


@router.post("/capabilities/drafts/{draft_id}/versions", include_in_schema=False)
def capability_platform_save_draft_version(
    draft_id: str,
    request: Request,
    version: str = Form(...),
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        draft_svc.save_draft_version(draft_id, version=version.strip())
        _set_flash(notice=f"Saved draft version {version.strip()}.")
    except CapabilityDraftNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    except ValueError as exc:
        _set_flash(error=str(exc))
    return RedirectResponse(url=_capability_platform_draft_path(draft_id), status_code=303)


@router.post("/capabilities/drafts/{draft_id}/validate", include_in_schema=False)
def capability_platform_validate_draft(
    draft_id: str,
    request: Request,
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        result = draft_svc.validate_draft(draft_id)
    except CapabilityDraftNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    _set_flash(
        notice=f"Validation complete: {result['passed']} passed, {result['failed']} failed."
    )
    return RedirectResponse(url=_capability_platform_draft_path(draft_id), status_code=303)


@router.post("/capabilities/drafts/{draft_id}/publish", include_in_schema=False)
def capability_platform_publish_draft(
    draft_id: str,
    request: Request,
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        result = draft_svc.publish_draft(draft_id)
    except CapabilityDraftNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    if not result.get("ok"):
        _set_flash(error=result.get("error", "Publish failed."))
    else:
        _set_flash(
            notice=(
                "Draft published to live truth. "
                f"Installed {result['installed_live_count']}, "
                f"replaced {result['replaced_live_count']}."
            )
        )
    return RedirectResponse(url=_capability_platform_draft_path(draft_id), status_code=303)


@router.post(
    "/capabilities/drafts/{draft_id}/rollback/revisions/{revision_id}",
    include_in_schema=False,
)
def capability_platform_rollback_revision(
    draft_id: str,
    revision_id: str,
    request: Request,
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        result = draft_svc.rollback_draft_to_revision(draft_id, revision_id)
    except CapabilityDraftNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    except KeyError:
        _set_flash(error="Draft revision not found.")
        return RedirectResponse(
            url=_capability_platform_draft_path(draft_id), status_code=303
        )
    target_draft_id = result.get("rollback_draft_id", draft_id)
    if not result.get("ok"):
        _set_flash(error=result.get("error", "Rollback failed."))
    else:
        _set_flash(
            notice="Rollback draft created and republished from the selected saved revision."
        )
    return RedirectResponse(
        url=_capability_platform_draft_path(target_draft_id), status_code=303
    )


@router.post(
    "/capabilities/drafts/{draft_id}/rollback/publications/{history_id}",
    include_in_schema=False,
)
def capability_platform_rollback_publication(
    draft_id: str,
    history_id: str,
    request: Request,
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        result = draft_svc.rollback_draft_to_publication(draft_id, history_id)
    except CapabilityDraftNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    except KeyError:
        _set_flash(error="Draft publication record not found.")
        return RedirectResponse(
            url=_capability_platform_draft_path(draft_id), status_code=303
        )
    target_draft_id = result.get("rollback_draft_id", draft_id)
    if not result.get("ok"):
        _set_flash(error=result.get("error", "Rollback failed."))
    else:
        _set_flash(
            notice=(
                "Rollback draft created and republished from the selected publication record."
            )
        )
    return RedirectResponse(
        url=_capability_platform_draft_path(target_draft_id), status_code=303
    )


@router.post("/capabilities/drafts/{draft_id}/items", include_in_schema=False)
def capability_platform_add_draft_item(
    draft_id: str,
    request: Request,
    planned_capability_id: str = Form(...),
    draft_data_json: str = Form(...),
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        draft_data = _parse_object_json(draft_data_json, field_name="Draft item JSON")
        if not planned_capability_id.strip():
            raise ValueError("planned_capability_id is required.")
        draft_svc.add_draft_item(
            draft_id,
            planned_capability_id=planned_capability_id.strip(),
            draft_data=draft_data,
        )
        _set_flash(notice="Draft item added.")
    except CapabilityDraftNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    except ValueError as exc:
        _set_flash(error=str(exc))
    return RedirectResponse(url=_capability_platform_draft_path(draft_id), status_code=303)


@router.post("/capabilities/drafts/{draft_id}/items/{item_id}", include_in_schema=False)
def capability_platform_update_draft_item(
    draft_id: str,
    item_id: str,
    request: Request,
    planned_capability_id: str = Form(...),
    draft_data_json: str = Form(...),
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        existing = draft_svc.get_draft_item_or_raise(item_id)
        if existing.draft_id != draft_id:
            return RedirectResponse(url="/capabilities", status_code=303)
        draft_data = _parse_object_json(draft_data_json, field_name="Draft item JSON")
        if not planned_capability_id.strip():
            raise ValueError("planned_capability_id is required.")
        draft_svc.update_draft_item(
            item_id,
            planned_capability_id=planned_capability_id.strip(),
            draft_data=draft_data,
        )
        _set_flash(notice="Draft item updated.")
    except KeyError:
        return RedirectResponse(url="/capabilities", status_code=303)
    except ValueError as exc:
        _set_flash(error=str(exc))
    return RedirectResponse(url=_capability_platform_draft_path(draft_id), status_code=303)


@router.post(
    "/capabilities/drafts/{draft_id}/items/{item_id}/delete",
    include_in_schema=False,
)
def capability_platform_remove_draft_item(
    draft_id: str,
    item_id: str,
    request: Request,
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        existing = draft_svc.get_draft_item_or_raise(item_id)
        if existing.draft_id != draft_id:
            return RedirectResponse(url="/capabilities", status_code=303)
        draft_svc.remove_draft_item(item_id)
    except KeyError:
        return RedirectResponse(url="/capabilities", status_code=303)
    _set_flash(notice="Draft item removed.")
    return RedirectResponse(url=_capability_platform_draft_path(draft_id), status_code=303)


@router.get("/capabilities/live/{capability_id}", include_in_schema=False)
def capability_platform_live_capability(capability_id: str):
    return RedirectResponse(
        url=f"/capabilities/{capability_id}/package", status_code=301
    )


@router.post("/capabilities/live/{capability_id}/drafts", include_in_schema=False)
def capability_platform_copy_live_capability_to_draft(
    capability_id: str,
    request: Request,
    draft_svc: CapabilityDraftService = Depends(get_capability_draft_service),
    catalog_svc: CapabilityCatalogService = Depends(get_capability_catalog_service),
):
    try:
        seed = catalog_svc.build_draft_seed_from_installed_capability(capability_id)
    except CapabilityRecordNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    draft = draft_svc.create_draft(
        name=seed["draft_name"],
        description=seed["draft_description"],
        version=seed["draft_data"].get("version", "1.0.0"),
    )
    draft_svc.add_draft_item(
        draft.id,
        planned_capability_id=seed["planned_capability_id"],
        draft_data=seed["draft_data"],
    )
    _set_flash(notice=f"Draft copied from installed capability {capability_id}.")
    return RedirectResponse(
        url=_capability_platform_draft_path(draft.id), status_code=303
    )


@router.get(
    "/capabilities/packages/{package_object_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capability_platform_package_object(
    package_object_id: str,
    request: Request,
    catalog_svc: CapabilityCatalogService = Depends(get_capability_catalog_service),
):
    try:
        package_object = catalog_svc.get_package_object_or_raise(package_object_id)
    except CapabilityRecordNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    return RedirectResponse(
        url=_capability_package_page_path(package_object.capability_id),
        status_code=301,
    )


@router.get(
    "/capabilities/{capability_id}/package",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capability_package_page(
    capability_id: str,
    request: Request,
    package_svc: CapabilityPackageService = Depends(get_capability_package_service),
):
    try:
        context = _build_capability_package_page_context(
            request=request,
            package_svc=package_svc,
            capability_id=capability_id,
        )
    except CapabilityRecordNotFoundError:
        return RedirectResponse(url="/capabilities", status_code=303)
    return templates.TemplateResponse(
        request,
        "capabilities/capability_package.html",
        context=context,
    )


@router.get("/capabilities/platform", response_class=HTMLResponse, include_in_schema=False)
def capability_platform_admin(
    request: Request,
    catalog: CapabilityCatalogService = Depends(get_capability_catalog_service),
):
    source_registrations = catalog.list_source_registrations()

    published_forms_catalog: list[dict] = []
    publication_pipeline: list[dict] = []
    entrypoint_registry: list[dict] = []
    event_summary: list[dict] = []
    surface_policies: list[dict] = []

    with get_db() as conn:
        try:
            rows = conn.execute(
                """
                SELECT form_kind, COUNT(*) AS form_count, MAX(created_at) AS last_generated
                FROM capability_published_forms
                GROUP BY form_kind
                ORDER BY form_count DESC
                """
            ).fetchall()
            published_forms_catalog = [
                {
                    "form_kind": row["form_kind"],
                    "form_count": row["form_count"],
                    "last_generated": row["last_generated"],
                }
                for row in rows
            ]
        except Exception:
            pass

        try:
            rows = conn.execute(
                """
                SELECT history_id, publication_state, executable_ready, created_at
                FROM capability_publication_candidates
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
            publication_pipeline = [
                {
                    "history_id": row["history_id"],
                    "publication_state": row["publication_state"],
                    "executable_ready": bool(row["executable_ready"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        except Exception:
            pass

        try:
            rows = conn.execute(
                """
                SELECT entrypoint, COUNT(*) AS capability_count
                FROM capability_records
                WHERE lifecycle_state = 'installed'
                GROUP BY entrypoint
                ORDER BY capability_count DESC
                """
            ).fetchall()
            entrypoint_registry = [
                {
                    "entrypoint": row["entrypoint"] or "run",
                    "capability_count": row["capability_count"],
                }
                for row in rows
            ]
        except Exception:
            pass

        try:
            rows = conn.execute(
                """
                SELECT event_type, COUNT(*) AS event_count, MAX(created_at) AS last_at
                FROM capability_record_events
                GROUP BY event_type
                ORDER BY event_count DESC
                """
            ).fetchall()
            event_summary = [
                {
                    "event_type": row["event_type"],
                    "event_count": row["event_count"],
                    "last_at": row["last_at"],
                }
                for row in rows
            ]
        except Exception:
            pass

        try:
            rows = conn.execute(
                """
                SELECT id, capability_id, surface_name, consumer_kind, access_policy, notes, created_at
                FROM capability_surface_policies
                ORDER BY surface_name ASC, consumer_kind ASC
                """
            ).fetchall()
            surface_policies = [
                {
                    "id": row["id"],
                    "capability_id": row["capability_id"],
                    "surface_name": row["surface_name"],
                    "consumer_kind": row["consumer_kind"],
                    "access_policy": row["access_policy"],
                    "notes": row["notes"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        except Exception:
            pass

    return templates.TemplateResponse(
        request,
        "capabilities/platform_admin.html",
        context={
            "active_nav": "capabilities",
            "return_to": "/capabilities",
            "return_label": "Capabilities",
            "return_to_query": "",
            "workspace_href": _capabilities_entry_path(),
            "source_registrations": source_registrations,
            "published_forms_catalog": published_forms_catalog,
            "publication_pipeline": publication_pipeline,
            "entrypoint_registry": entrypoint_registry,
            "event_summary": event_summary,
            "surface_policies": surface_policies,
            **_consume_flash(),
        },
    )


# ---------------------------------------------------------------------------
# Capability Environment
# ---------------------------------------------------------------------------

@router.get("/capability-environment/launch", include_in_schema=False)
def capability_environment_launch(request: Request):
    return RedirectResponse(url=_capability_environment_entry_path(), status_code=303)


@router.get(
    "/capability-environment/skins/{skin_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capability_environment_skin_direct(
    skin_id: str,
    request: Request,
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    raw_station = request.query_params.get("station", "").strip()
    active_station = resolve_capability_environment_station_action(raw_station)
    if active_station not in {"create_draft", "inventory_wall", "workbench", "ledger", "dispatch_bench"}:
        active_station = None
    selected_draft_id = request.query_params.get("draft", "").strip() or None
    selected_skin = CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID.get(skin_id)
    if selected_skin is None:
        return _render_missing_environment_skin(
            request=request,
            env_svc=env_svc,
            skin_id=skin_id,
        )
    return _render_capability_environment_place(
        request=request,
        env_svc=env_svc,
        selected_skin=selected_skin,
        base_path=f"/capability-environment/skins/{skin_id}",
        active_station=active_station,
        selected_draft_id=selected_draft_id,
    )


@router.get(
    "/capability-environment/professional",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capability_environment_professional(request: Request):
    return RedirectResponse(url=_capabilities_professional_path(), status_code=303)


@router.get(
    "/capability-environment/settings",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capability_environment_settings(request: Request):
    return RedirectResponse(url=_capabilities_settings_path(), status_code=303)


@router.post("/capability-environment/settings", include_in_schema=False)
def capability_environment_settings_update(
    request: Request,
    enable_skins: str | None = Form(None),
    selected_skin_id: str = Form("random"),
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    env_svc.update_settings(
        enable_skins=enable_skins is not None and enable_skins not in ("", "false", "0"),
        selected_skin_id=selected_skin_id,
    )
    return RedirectResponse(url=_capabilities_settings_path(), status_code=303)


@router.get(
    "/capability-environment/stations/{station_segment}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capability_environment_station(
    station_segment: str,
    request: Request,
):
    active_station = resolve_capability_environment_station_action(station_segment)
    if active_station not in {"create_draft", "inventory_wall", "workbench", "ledger", "dispatch_bench"}:
        return RedirectResponse(url="/capability-environment")
    selected_draft_id = request.query_params.get("draft", "").strip() or None
    return RedirectResponse(
        url=_capability_environment_scene_path(
            "/capability-environment",
            station=active_station,
            draft_id=selected_draft_id,
        ),
        status_code=303,
    )


@router.get(
    "/capability-environment/drafts/{draft_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capability_draft_detail(
    draft_id: str,
    request: Request,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        svc.get_draft_or_raise(draft_id)
    except CapabilityDraftNotFoundError:
        return RedirectResponse(url="/capability-environment")

    active_station = _resolve_cap_env_station(request, default="workbench")
    if active_station not in {"workbench", "ledger", "dispatch_bench"}:
        active_station = "workbench"
    return RedirectResponse(
        url=_capability_environment_scene_path(
            "/capability-environment",
            station=active_station,
            draft_id=draft_id,
        ),
        status_code=303,
    )


@router.get(
    "/capability-environment",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def capability_environment(
    request: Request,
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    raw_station = request.query_params.get("station", "").strip()
    active_station = resolve_capability_environment_station_action(raw_station)
    if active_station not in {"create_draft", "inventory_wall", "workbench", "ledger", "dispatch_bench"}:
        active_station = None
    selected_draft_id = request.query_params.get("draft", "").strip() or None

    selected_skin = env_svc.resolve_entry_skin_package()
    if selected_skin is not None:
        return RedirectResponse(
            url=_capability_environment_skin_path(
                selected_skin.skin_id,
                station=active_station,
                draft_id=selected_draft_id,
            ),
            status_code=303,
        )

    return _render_capability_environment_place(
        request=request,
        env_svc=env_svc,
        selected_skin=None,
        base_path="/capability-environment",
        active_station=active_station,
        selected_draft_id=selected_draft_id,
    )
