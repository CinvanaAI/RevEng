"""
Capability Environment API routes.

These routes expose Capability Platform draft authority plus bounded
Capability-Environment orchestration. Draft truth stays platform-owned;
environment-local station behavior composes that truth without mutating the
live installed registry.

Route prefix: /api/capability-environment
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from reveng.execution_environment.capability_environment import (
    CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID,
    CapabilityEnvironmentService,
)
from reveng.platform.models.capability_draft import CapabilityDraftNotFoundError
from reveng.platform.services.capability_catalog_service import CapabilityCatalogService
from reveng.platform.services.draft_service import (
    COMBINATION_LOGIC_KINDS,
    CapabilityDraftService,
)
from reveng.platform.web.deps import (
    get_capability_draft_service,
    get_capability_catalog_service,
    get_capability_environment_service,
)

router = APIRouter()


class CreateDraftBody(BaseModel):
    name: str
    description: str = ""


class UpdateDraftBody(BaseModel):
    name: str | None = None
    description: str | None = None


class SaveDraftVersionBody(BaseModel):
    version: str


class AddDraftItemBody(BaseModel):
    planned_capability_id: str
    draft_data: dict[str, Any] = {}


class UpdateDraftItemBody(BaseModel):
    planned_capability_id: str | None = None
    draft_data: dict[str, Any] | None = None


class CopyInstalledCapabilityToDraftBody(BaseModel):
    capability_id: str


@router.get("/drafts")
def list_drafts(
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    drafts = svc.list_drafts()
    return {"drafts": [_draft_dict(draft) for draft in drafts]}


@router.post("/drafts", status_code=201)
def create_draft(
    body: CreateDraftBody,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    draft = svc.create_draft(name=body.name, description=body.description)
    return _draft_dict(draft)


@router.post("/stations/create-draft", status_code=201)
def create_draft_from_environment_station(
    body: CreateDraftBody,
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    try:
        draft = env_svc.create_intentional_draft(
            name=body.name,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _draft_dict(draft)


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        spec = svc.get_draft_spec(draft_id)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {
        **_draft_dict(spec.draft),
        "items": [_draft_item_dict(item) for item in spec.items],
    }


@router.patch("/drafts/{draft_id}")
def update_draft(
    draft_id: str,
    body: UpdateDraftBody,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        draft = svc.update_draft(
            draft_id,
            name=body.name,
            description=body.description,
        )
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _draft_dict(draft)


@router.delete("/drafts/{draft_id}", status_code=204)
def delete_draft(
    draft_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        svc.delete_draft(draft_id)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")


@router.post("/drafts/{draft_id}/versions", status_code=201)
def save_draft_version(
    draft_id: str,
    body: SaveDraftVersionBody,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        revision = svc.save_draft_version(draft_id, version=body.version)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _draft_revision_dict(revision)


@router.post("/drafts/{draft_id}/items", status_code=201)
def add_draft_item(
    draft_id: str,
    body: AddDraftItemBody,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        item = svc.add_draft_item(
            draft_id,
            planned_capability_id=body.planned_capability_id,
            draft_data=body.draft_data,
        )
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _draft_item_dict(item)


@router.patch("/drafts/{draft_id}/items/{item_id}")
def update_draft_item(
    draft_id: str,
    item_id: str,
    body: UpdateDraftItemBody,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        existing = svc.get_draft_item_or_raise(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Draft item not found")
    if existing.draft_id != draft_id:
        raise HTTPException(status_code=404, detail="Draft item not found")

    item = svc.update_draft_item(
        item_id,
        planned_capability_id=body.planned_capability_id,
        draft_data=body.draft_data,
    )
    return _draft_item_dict(item)


@router.delete("/drafts/{draft_id}/items/{item_id}", status_code=204)
def remove_draft_item(
    draft_id: str,
    item_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        existing = svc.get_draft_item_or_raise(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Draft item not found")
    if existing.draft_id != draft_id:
        raise HTTPException(status_code=404, detail="Draft item not found")
    svc.remove_draft_item(item_id)


@router.post("/drafts/{draft_id}/validate")
def validate_draft(
    draft_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        svc.get_draft_or_raise(draft_id)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    return svc.validate_draft(draft_id)


@router.post("/drafts/{draft_id}/publish")
def publish_draft(
    draft_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        svc.get_draft_or_raise(draft_id)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    result = svc.publish_draft(draft_id)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Publish failed"))
    return result


@router.post("/drafts/{draft_id}/rollback/revisions/{revision_id}")
def rollback_draft_revision(
    draft_id: str,
    revision_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        svc.get_draft_or_raise(draft_id)
        result = svc.rollback_draft_to_revision(draft_id, revision_id)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Draft revision not found")
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result)
    return result


@router.post("/drafts/{draft_id}/rollback/publications/{history_id}")
def rollback_draft_publication(
    draft_id: str,
    history_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        svc.get_draft_or_raise(draft_id)
        result = svc.rollback_draft_to_publication(draft_id, history_id)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    except KeyError:
        raise HTTPException(status_code=404, detail="Draft publication record not found")
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result)
    return result


@router.get("/drafts/{draft_id}/revisions")
def draft_revision_history(
    draft_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        svc.get_draft_or_raise(draft_id)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    records = svc.get_draft_revision_history(draft_id)
    return {
        "draft_id": draft_id,
        "revisions": [_draft_revision_dict(record) for record in records],
    }


@router.get("/drafts/{draft_id}/history")
def draft_publication_history(
    draft_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        svc.get_draft_or_raise(draft_id)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    records = svc.get_draft_publication_history(draft_id)
    history = [
        {
            "id": record.id,
            "version": record.version,
            "published_at": record.published_at,
            "item_count": record.item_count,
        }
        for record in records
    ]
    return {
        "draft_id": draft_id,
        "history": history,
    }


@router.get("/drafts/{draft_id}/export")
def export_draft(
    draft_id: str,
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
):
    try:
        svc.get_draft_or_raise(draft_id)
    except CapabilityDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")
    snippet = svc.export_draft_as_pack_snippet(draft_id)
    return {"draft_id": draft_id, "snippet": snippet}


@router.get("/settings")
def get_settings(
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    """Return the current capability environment settings (enable_skins, selected_skin_id)."""
    settings = env_svc.get_settings()
    return {
        "enable_skins": settings.enable_skins,
        "selected_skin_id": settings.selected_skin_id,
        "selected_skin_label": settings.selected_skin_label,
        "updated_at": settings.updated_at,
    }


class UpdateSettingsBody(BaseModel):
    enable_skins: bool
    selected_skin_id: str = "random"


@router.post("/settings")
def update_settings(
    body: UpdateSettingsBody,
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    """Update capability environment settings."""
    settings = env_svc.update_settings(
        enable_skins=body.enable_skins,
        selected_skin_id=body.selected_skin_id,
    )
    return {
        "enable_skins": settings.enable_skins,
        "selected_skin_id": settings.selected_skin_id,
        "selected_skin_label": settings.selected_skin_label,
        "updated_at": settings.updated_at,
    }


@router.get("/skins")
def list_skins(
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    """Return all available capability environment skin packages as JSON."""
    skins = []
    for pkg in CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID.values():
        skins.append({
            "skin_id": pkg.skin_id,
            "surface_title": pkg.surface_title,
            "surface_image_url": pkg.surface_image_url,
            "tone": getattr(pkg, "tone", "neutral"),
            "hotspots": [
                {
                    "action_id": h.action_id,
                    "display_label": h.display_label,
                    "left_pct": h.left_pct,
                    "top_pct": h.top_pct,
                    "width_pct": h.width_pct,
                    "height_pct": h.height_pct,
                }
                for h in pkg.hotspots
            ],
        })
    # Expose active (resolved) skin
    resolved = env_svc.resolve_entry_skin_package()
    return {
        "skins": skins,
        "active_skin_id": resolved.skin_id if resolved else None,
    }


@router.get("/combination-logic-kinds")
def combination_logic_kinds():
    return {
        "kinds": [
            {"kind": kind, "description": description}
            for kind, description in COMBINATION_LOGIC_KINDS.items()
        ]
    }


@router.get("/context")
def environment_context(
    svc: CapabilityDraftService = Depends(get_capability_draft_service),
    catalog: CapabilityCatalogService = Depends(get_capability_catalog_service),
):
    """
    Machine-readable Capability Environment snapshot for automation tooling.

    This returns draft counts, active draft work, and installed capability
    inventory counts without assigning any agent ownership to the environment.
    """
    all_drafts = svc.list_drafts()
    counts: dict[str, int] = {}
    for draft in all_drafts:
        counts[draft.lifecycle_state] = counts.get(draft.lifecycle_state, 0) + 1

    active_drafts = [draft for draft in all_drafts if draft.lifecycle_state == "draft"]
    active_work = [
        {
            "draft_id": draft.id,
            "name": draft.name,
            "version": draft.version,
            "item_count": len(svc.list_draft_items(draft.id)),
        }
        for draft in active_drafts
    ]

    installed_ids = catalog.list_installed_capability_ids()

    return {
        "draft_counts": counts,
        "total_drafts": len(all_drafts),
        "active_work": active_work,
        "installed_capability_count": len(installed_ids),
        "installed_capability_ids": sorted(installed_ids),
    }


@router.get("/platform-inventory")
def platform_inventory(
    catalog: CapabilityCatalogService = Depends(get_capability_catalog_service),
):
    caps = catalog.list_installed_inventory_entries()
    return {
        "installed_count": len(caps),
        "capabilities": caps,
    }


@router.get("/inventory/{capability_id}")
def installed_capability_detail(
    capability_id: str,
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    try:
        return env_svc.get_installed_capability_detail(capability_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Installed capability not found")


@router.post("/inventory/copy-to-draft", status_code=201)
def copy_installed_capability_to_draft(
    body: CopyInstalledCapabilityToDraftBody,
    env_svc: CapabilityEnvironmentService = Depends(get_capability_environment_service),
):
    try:
        draft = env_svc.create_draft_from_installed_capability(body.capability_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Installed capability not found")
    return _draft_dict(draft)


def _draft_dict(draft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "draft_id": draft.id,
        "name": draft.name,
        "description": draft.description,
        "lifecycle_state": draft.lifecycle_state,
        "version": draft.version,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
    }


def _draft_item_dict(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "draft_id": item.draft_id,
        "planned_capability_id": item.planned_capability_id,
        "draft_data": item.draft_data,
        "item_state": item.item_state,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _draft_revision_dict(record) -> dict[str, Any]:
    return {
        "id": record.id,
        "draft_id": record.draft_id,
        "version": record.version,
        "name": record.name,
        "description": record.description,
        "saved_at": record.saved_at,
        "item_count": record.item_count,
        "snapshot_data": record.snapshot_data,
    }
