"""
Capability Platform API routes.

These routes expose Platform-owned capability catalog truth directly, without
wrapping it in any environment-local station semantics.

Surface gating
--------------
Every route checks CapabilitySurfacePolicyService before serving.  The default
policy is allow (open by default unless an explicit deny or require_gate policy
exists).  consumer_kind is 'api_consumer' for all router-level checks.

Canonical surface names:
  inventory          GET /                       list installed catalog
  installed_record   GET /{id}                   installed detail
                     GET /{id}/draft-seed        seed for draft creation
  published_source   GET /{id}/body              code_block from installed record
  history            GET /{id}/history           immutable record event ledger
  package            GET /{id}/package           full two-surface package object
  published_artifact GET /{id}/published-forms   artifact index rows
  unpublished_edits  POST /{id}/propose          open a draft edit
                     POST /{id}/validate         validate open draft
                     DELETE /{id}/draft          discard open draft
  publish_operation  POST /{id}/publish          publish open draft
                     POST /{id}/rollback         roll back to prior publication
                     POST /changeset/publish     coordinated multi-cap publish
"""
from __future__ import annotations

from dataclasses import asdict
from contextlib import contextmanager
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from reveng.platform.services.capability_catalog_service import (
    CapabilityCatalogService,
    CapabilityRecordNotFoundError,
)
from reveng.platform.services.capability_package_service import CapabilityPackageService
from reveng.platform.services.capability_surface_policy_service import CapabilitySurfacePolicyService
from reveng.platform.services.draft_service import CapabilityDraftService
from reveng.platform.web.deps import (
    get_capability_catalog_service,
    get_capability_draft_service,
    get_capability_package_service,
    get_capability_surface_policy_service,
)
from reveng.storage.system_db import ensure_system_db_ready

router = APIRouter()

_CONSUMER_KIND = "api_consumer"


@contextmanager
def get_db():
    db_path = ensure_system_db_ready()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _gate(
    gate: CapabilitySurfacePolicyService,
    capability_id: str | None,
    surface_name: str,
) -> None:
    """Raise 403 if the surface policy denies access."""
    if not gate.check(capability_id, surface_name, _CONSUMER_KIND):
        raise HTTPException(
            status_code=403,
            detail=f"Access to surface '{surface_name}' denied by capability surface policy.",
        )


class ProposeBody(BaseModel):
    draft_data: dict[str, Any]


class RollbackBody(BaseModel):
    history_id: str


class ChangesetBody(BaseModel):
    capability_ids: list[str]


@router.get("")
def list_installed_capabilities(
    catalog: CapabilityCatalogService = Depends(get_capability_catalog_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    _gate(gate, None, "inventory")
    capabilities = catalog.list_installed_inventory_entries()
    return {
        "installed_count": len(capabilities),
        "capabilities": capabilities,
    }


@router.get("/{capability_id}")
def get_installed_capability(
    capability_id: str,
    catalog: CapabilityCatalogService = Depends(get_capability_catalog_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    _gate(gate, capability_id, "installed_record")
    try:
        return catalog.get_installed_capability_detail(capability_id)
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")


@router.get("/{capability_id}/draft-seed")
def get_installed_capability_draft_seed(
    capability_id: str,
    catalog: CapabilityCatalogService = Depends(get_capability_catalog_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    _gate(gate, capability_id, "installed_record")
    try:
        return catalog.build_draft_seed_from_installed_capability(capability_id)
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")


@router.get("/{capability_id}/body")
def get_capability_body(
    capability_id: str,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Return the canonical code_block for the capability."""
    _gate(gate, capability_id, "published_source")
    try:
        body = packages.get_body(capability_id)
        return {"capability_id": capability_id, "code_block": body}
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")


@router.get("/{capability_id}/history")
def get_capability_history(
    capability_id: str,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Return the full immutable record event ledger for the capability."""
    _gate(gate, capability_id, "history")
    try:
        history = packages.get_history(capability_id)
        return {
            "capability_id": capability_id,
            "event_count": len(history),
            "events": [asdict(e) for e in history],
        }
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")


@router.get("/{capability_id}/package")
def get_capability_package(
    capability_id: str,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Return the full package: published surface, unpublished surface (if any), and history."""
    _gate(gate, capability_id, "package")
    try:
        pkg = packages.get_package(capability_id)
        unpublished = None
        if pkg.unpublished is not None:
            u = pkg.unpublished
            unpublished = {
                "draft_id": u.draft_id,
                "draft_name": u.draft_name,
                "item_id": u.item_id,
                "draft_data": u.draft_data,
                "status": u.status,
            }
        return {
            "capability_id": pkg.capability_id,
            "published": asdict(pkg.published),
            "unpublished": unpublished,
            "history": [asdict(e) for e in pkg.history],
        }
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")


@router.get("/{capability_id}/published-forms")
def get_capability_published_forms(
    capability_id: str,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Return all package-owned published artifact forms for a capability."""
    _gate(gate, capability_id, "published_artifact")
    try:
        forms = packages.get_published_forms(capability_id)
        return {
            "capability_id": capability_id,
            "forms": [asdict(f) for f in forms],
        }
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")


@router.post("/{capability_id}/propose")
def propose_package_edit(
    capability_id: str,
    body: ProposeBody,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    drafts: CapabilityDraftService = Depends(get_capability_draft_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Open a new draft for a single capability package edit."""
    _gate(gate, capability_id, "unpublished_edits")
    try:
        return packages.propose(capability_id, body.draft_data, draft_service=drafts)
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{capability_id}/validate")
def validate_package_draft(
    capability_id: str,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    drafts: CapabilityDraftService = Depends(get_capability_draft_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Validate the open draft for a capability package."""
    _gate(gate, capability_id, "unpublished_edits")
    try:
        return packages.validate_draft_for(capability_id, draft_service=drafts)
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{capability_id}/publish")
def publish_package_draft(
    capability_id: str,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    drafts: CapabilityDraftService = Depends(get_capability_draft_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Publish the open draft for a capability package."""
    _gate(gate, capability_id, "publish_operation")
    try:
        return packages.publish_draft_for(capability_id, draft_service=drafts)
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{capability_id}/rollback")
def rollback_package(
    capability_id: str,
    body: RollbackBody,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    drafts: CapabilityDraftService = Depends(get_capability_draft_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Roll back a capability package to a previous publication."""
    _gate(gate, capability_id, "publish_operation")
    try:
        return packages.rollback_to_publication(
            capability_id, body.history_id, draft_service=drafts
        )
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/{capability_id}/draft")
def discard_package_draft(
    capability_id: str,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    drafts: CapabilityDraftService = Depends(get_capability_draft_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Discard (delete) the open draft for a capability package."""
    _gate(gate, capability_id, "unpublished_edits")
    try:
        packages.discard_draft_for(capability_id, draft_service=drafts)
        return {"status": "discarded", "capability_id": capability_id}
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/platform-admin")
def platform_admin_data(
    catalog: CapabilityCatalogService = Depends(get_capability_catalog_service),
):
    """
    Read-only observability snapshot of Capability Platform internals.
    Returns source registrations, published forms catalog, publication pipeline,
    entrypoint registry, event summary, and surface policies.
    """
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
                {"form_kind": r["form_kind"], "form_count": r["form_count"], "last_generated": r["last_generated"]}
                for r in rows
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
                    "history_id": r["history_id"],
                    "publication_state": r["publication_state"],
                    "executable_ready": bool(r["executable_ready"]),
                    "created_at": r["created_at"],
                }
                for r in rows
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
                {"entrypoint": r["entrypoint"] or "run", "capability_count": r["capability_count"]}
                for r in rows
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
                {"event_type": r["event_type"], "event_count": r["event_count"], "last_at": r["last_at"]}
                for r in rows
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
                    "id": r["id"],
                    "capability_id": r["capability_id"],
                    "surface_name": r["surface_name"],
                    "consumer_kind": r["consumer_kind"],
                    "access_policy": r["access_policy"],
                    "notes": r["notes"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        except Exception:
            pass

    return {
        "source_registrations": source_registrations,
        "published_forms_catalog": published_forms_catalog,
        "publication_pipeline": publication_pipeline,
        "entrypoint_registry": entrypoint_registry,
        "event_summary": event_summary,
        "surface_policies": surface_policies,
    }


@router.post("/changeset/publish")
def publish_changeset(
    body: ChangesetBody,
    packages: CapabilityPackageService = Depends(get_capability_package_service),
    drafts: CapabilityDraftService = Depends(get_capability_draft_service),
    gate: CapabilitySurfacePolicyService = Depends(get_capability_surface_policy_service),
):
    """Publish a coordinated multi-capability changeset atomically."""
    _gate(gate, None, "publish_operation")
    try:
        return packages.publish_changeset(body.capability_ids, draft_service=drafts)
    except CapabilityRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Installed capability not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
