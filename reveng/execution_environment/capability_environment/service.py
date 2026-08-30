"""Capability Environment application service."""
from __future__ import annotations

from typing import Any

from reveng.execution_environment.capability_environment.stations import (
    CAPABILITY_ENVIRONMENT_STATION_BY_ACTION,
    build_capability_environment_station_href,
)
from reveng.execution_environment.capability_environment.settings import (
    CapabilityEnvironmentSettingsService,
)
from reveng.platform.models.capability_draft import (
    CapabilityDraftNotFoundError,
    CapabilityDraftRecord,
)
from reveng.platform.services.capability_catalog_service import (
    CapabilityCatalogService,
    CapabilityRecordNotFoundError,
)
from reveng.platform.services.draft_service import COMBINATION_LOGIC_KINDS, CapabilityDraftService


class CapabilityEnvironmentService:
    """
    Environment-local application service for Capability Environment.

    This service owns station meanings, station navigation, environment-local
    context assembly, and bounded orchestration such as seeding a draft from
    installed inventory. Draft truth itself remains delegated to the platform
    draft authority service.
    """

    def __init__(
        self,
        draft_authority: CapabilityDraftService,
        capability_catalog: CapabilityCatalogService | None = None,
        settings_service: CapabilityEnvironmentSettingsService | None = None,
    ) -> None:
        self._draft_authority = draft_authority
        self._capability_catalog = capability_catalog or CapabilityCatalogService()
        self._settings = settings_service or CapabilityEnvironmentSettingsService()

    # ------------------------------------------------------------------
    # Station routing
    # ------------------------------------------------------------------

    def build_station_urls(
        self,
        *,
        base_path: str,
        return_to_query: str,
        current_draft: CapabilityDraftRecord | None = None,
        selected_draft_id: str | None = None,
        return_to: str,
    ) -> dict[str, str]:
        draft_id = current_draft.id if current_draft is not None else None
        urls = {
            action_id: build_capability_environment_station_href(
                action_id,
                base_path=base_path,
                return_to_query=return_to_query,
                draft_id=draft_id,
                selected_draft_id=selected_draft_id,
            )
            for action_id, station in CAPABILITY_ENVIRONMENT_STATION_BY_ACTION.items()
            if station.navigable
        }
        urls["return"] = return_to
        return urls

    def build_skin_action_links(
        self,
        *,
        base_path: str,
        return_to_query: str,
        return_to: str,
    ) -> dict[str, str]:
        station_urls = self.build_station_urls(
            base_path=base_path,
            return_to_query=return_to_query,
            current_draft=None,
            selected_draft_id=None,
            return_to=return_to,
        )
        return {
            "create_draft": station_urls["create_draft"],
            "inventory_wall": station_urls["inventory_wall"],
            "workbench": station_urls["workbench"],
            "ledger": station_urls["ledger"],
            "dispatch_bench": station_urls["dispatch_bench"],
            "return": return_to,
        }

    def build_environment_entry_href(
        self,
        *,
        base_path: str,
        return_to_query: str,
    ) -> str:
        if not return_to_query:
            return base_path
        return f"{base_path}?return={return_to_query}"

    def build_draft_station_urls(
        self,
        *,
        base_path: str,
        draft_ids: list[str],
        return_to_query: str,
    ) -> dict[str, dict[str, str]]:
        urls: dict[str, dict[str, str]] = {}
        for draft_id in draft_ids:
            urls[draft_id] = {
                "workbench": build_capability_environment_station_href(
                    "workbench",
                    base_path=base_path,
                    return_to_query=return_to_query,
                    selected_draft_id=draft_id,
                ),
                "ledger": build_capability_environment_station_href(
                    "ledger",
                    base_path=base_path,
                    return_to_query=return_to_query,
                    selected_draft_id=draft_id,
                ),
                "dispatch_bench": build_capability_environment_station_href(
                    "dispatch_bench",
                    base_path=base_path,
                    return_to_query=return_to_query,
                    selected_draft_id=draft_id,
                ),
            }
        return urls

    def get_settings(self):
        return self._settings.get_settings()

    def update_settings(
        self,
        *,
        enable_skins: bool,
        selected_skin_id: str,
    ):
        return self._settings.update_settings(
            enable_skins=enable_skins,
            selected_skin_id=selected_skin_id,
        )

    def list_skin_options(self) -> list[dict[str, str]]:
        return self._settings.list_skin_options()

    def resolve_entry_skin_package(self, *, rng=None):
        settings = self.get_settings()
        if not settings.enable_skins:
            return None
        if settings.selected_skin_id == "random":
            from reveng.execution_environment.capability_environment.skins import (
                choose_random_capability_environment_skin_package,
            )
            return choose_random_capability_environment_skin_package(rng=rng)
        from reveng.execution_environment.capability_environment.skins import (
            CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID,
        )
        return CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID.get(settings.selected_skin_id)

    # ------------------------------------------------------------------
    # Station context
    # ------------------------------------------------------------------

    def build_place_context(
        self,
        *,
        base_path: str,
        active_station: str | None,
        selected_draft_id: str | None,
        return_to: str,
        return_label: str,
        return_to_query: str,
        recent_draft_ids: list[str],
    ) -> dict[str, Any]:
        drafts = self._draft_authority.list_drafts()
        installed = self._load_installed_capabilities()
        settings = self.get_settings()
        selected_draft = self._resolve_selected_draft(selected_draft_id)
        selected_spec = (
            self._draft_authority.get_draft_spec(selected_draft.id)
            if selected_draft is not None
            else None
        )
        selected_history = (
            self._draft_authority.get_draft_publication_history(selected_draft.id)
            if selected_draft is not None
            else []
        )
        selected_candidates = (
            self._draft_authority.get_draft_publication_candidates(selected_draft.id)
            if selected_draft is not None
            else []
        )
        selected_revisions = (
            self._draft_authority.get_draft_revision_history(selected_draft.id)
            if selected_draft is not None
            else []
        )
        station_urls = self.build_station_urls(
            base_path=base_path,
            return_to_query=return_to_query,
            current_draft=selected_draft,
            selected_draft_id=None,
            return_to=return_to,
        )
        station_base_urls = self.build_station_urls(
            base_path=base_path,
            return_to_query=return_to_query,
            current_draft=None,
            selected_draft_id=None,
            return_to=return_to,
        )
        draft_station_urls = self.build_draft_station_urls(
            base_path=base_path,
            draft_ids=[draft.id for draft in drafts],
            return_to_query=return_to_query,
        )
        current_label = (
            CAPABILITY_ENVIRONMENT_STATION_BY_ACTION[active_station].display_name
            if active_station
            else "Environment Floor"
        )
        return {
            "active_station": active_station,
            "selected_station": CAPABILITY_ENVIRONMENT_STATION_BY_ACTION.get(active_station or ""),
            "drafts": drafts,
            "installed": installed,
            "return_to": return_to,
            "return_label": return_label,
            "return_to_query": return_to_query,
            "environment_entry_href": self.build_environment_entry_href(
                base_path=base_path,
                return_to_query=return_to_query,
            ),
            "close_surface_href": self.build_environment_entry_href(
                base_path=base_path,
                return_to_query=return_to_query,
            ),
            "draft_station_urls": draft_station_urls,
            "station_urls": station_urls,
            "station_base_urls": station_base_urls,
            "current_draft": selected_draft,
            "station_draft": selected_draft,
            "station_draft_spec": selected_spec,
            "station_draft_history": selected_history,
            "station_draft_publication_candidates": selected_candidates,
            "station_draft_revisions": selected_revisions,
            "spec": selected_spec,
            "draft": selected_draft,
            "items": selected_spec.items if selected_spec is not None else [],
            "history": selected_history,
            "revisions": selected_revisions,
            "environment_memory": self._build_named_environment_memory(
                current_label=current_label,
                recent_draft_ids=recent_draft_ids,
                current_draft=selected_draft,
                return_to_query=return_to_query,
            ),
            "environment_stats": self._environment_stats(
                drafts,
                installed_count=len(installed),
            ),
            "capability_environment_settings": settings,
            "combination_logic_kinds": COMBINATION_LOGIC_KINDS,
        }

    def build_settings_surface_context(
        self,
        *,
        return_to: str,
        return_label: str,
        return_to_query: str,
        recent_draft_ids: list[str],
    ) -> dict[str, Any]:
        drafts = self._draft_authority.list_drafts()
        installed = self._load_installed_capabilities()
        settings = self.get_settings()
        station_urls = self.build_station_urls(
            base_path="/capability-environment",
            return_to_query=return_to_query,
            current_draft=None,
            selected_draft_id=None,
            return_to=return_to,
        )
        return {
            "active_station": None,
            "drafts": drafts,
            "installed": installed,
            "return_to": return_to,
            "return_label": return_label,
            "return_to_query": return_to_query,
            "current_draft": None,
            "station_urls": station_urls,
            "environment_memory": self._build_named_environment_memory(
                current_label="Settings",
                recent_draft_ids=recent_draft_ids,
                current_draft=None,
                return_to_query=return_to_query,
            ),
            "environment_stats": self._environment_stats(
                drafts,
                installed_count=len(installed),
            ),
            "capability_environment_settings": settings,
            "skin_options": self.list_skin_options(),
        }

    # ------------------------------------------------------------------
    # Environment orchestration
    # ------------------------------------------------------------------

    def create_intentional_draft(
        self,
        *,
        name: str,
        description: str = "",
    ) -> CapabilityDraftRecord:
        draft_name = name.strip()
        if not draft_name:
            raise ValueError("Draft name is required.")
        return self._draft_authority.create_draft(
            name=draft_name,
            description=description.strip(),
        )

    def create_draft_from_installed_capability(self, capability_id: str):
        seed = self._build_draft_seed_from_installed_capability(capability_id)
        draft = self._draft_authority.create_draft(
            name=seed["draft_name"],
            description=seed["draft_description"],
        )
        self._draft_authority.add_draft_item(
            draft.id,
            planned_capability_id=seed["planned_capability_id"],
            draft_data=seed["draft_data"],
        )
        return draft

    def get_installed_capability_detail(self, capability_id: str) -> dict[str, Any]:
        try:
            return self._capability_catalog.get_installed_capability_detail(capability_id)
        except CapabilityRecordNotFoundError as exc:
            raise KeyError(f"Installed capability not found: {capability_id!r}") from exc

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_selected_draft(self, selected_draft_id: str | None):
        if not selected_draft_id:
            return None
        try:
            return self._draft_authority.get_draft_or_raise(selected_draft_id)
        except CapabilityDraftNotFoundError:
            return None

    def _load_installed_capabilities(self) -> list[dict[str, Any]]:
        return self._capability_catalog.list_installed_inventory_entries()

    def _build_draft_seed_from_installed_capability(self, capability_id: str) -> dict[str, Any]:
        try:
            return self._capability_catalog.build_draft_seed_from_installed_capability(capability_id)
        except CapabilityRecordNotFoundError as exc:
            raise KeyError(f"Installed capability not found: {capability_id!r}") from exc

    def _environment_stats(
        self,
        drafts,
        *,
        installed_count: int,
    ) -> dict[str, int]:
        active_drafts = len([draft for draft in drafts if draft.lifecycle_state == "draft"])
        published_drafts = len([draft for draft in drafts if draft.lifecycle_state == "published"])
        retired_drafts = len([draft for draft in drafts if draft.lifecycle_state == "retired"])
        return {
            "total_drafts": len(drafts),
            "active_drafts": active_drafts,
            "published_drafts": published_drafts,
            "retired_drafts": retired_drafts,
            "installed_count": installed_count,
        }

    def _build_named_environment_memory(
        self,
        *,
        current_label: str,
        recent_draft_ids: list[str],
        current_draft: CapabilityDraftRecord | None,
        return_to_query: str,
    ) -> dict[str, object]:
        recent_benches: list[dict[str, str]] = []
        for draft_id in recent_draft_ids:
            try:
                draft = self._draft_authority.get_draft_or_raise(draft_id)
            except CapabilityDraftNotFoundError:
                continue
            if current_draft is not None and draft.id == current_draft.id:
                continue
            href = build_capability_environment_station_href(
                "workbench",
                return_to_query=return_to_query,
                selected_draft_id=draft.id,
            )
            recent_benches.append(
                {
                    "id": draft.id,
                    "name": draft.name,
                    "href": href,
                    "state": draft.lifecycle_state,
                }
            )
            if len(recent_benches) >= 3:
                break

        return {
            "current_station": current_label,
            "current_draft": current_draft,
            "recent_benches": recent_benches,
        }


__all__ = ["CapabilityEnvironmentService"]
