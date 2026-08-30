"""
/api/providers — read-only provider listing.

Providers are configured via environment variables and seeded at startup.
A management UI for adding/editing providers comes in a later phase.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from reveng.platform.services.provider_service import ProviderService
from reveng.platform.web.deps import get_provider_service

router = APIRouter()


def _provider_dict(record) -> dict:
    return {
        "id": record.id,
        "kind": record.kind,
        "label": record.label,
        "base_url": record.base_url,
        "api_key_env": record.api_key_env,
        "is_default": record.is_default,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


@router.get("")
def list_providers(svc: ProviderService = Depends(get_provider_service)):
    providers = svc.list_all()
    return {"providers": [_provider_dict(p) for p in providers]}


@router.get("/{provider_id}")
def get_provider(provider_id: str, svc: ProviderService = Depends(get_provider_service)):
    record = svc.get(provider_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Provider not found: {provider_id}")
    return _provider_dict(record)
