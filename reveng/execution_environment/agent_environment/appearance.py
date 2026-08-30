"""Agent Environment skin/background asset and preference service."""
from __future__ import annotations

import random
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from reveng.storage.db_connection import get_db
from reveng.platform.models.agent_environment_agent_skin_preference import (
    AgentEnvironmentAgentSkinPreferenceRecord,
)
from reveng.platform.models.agent_environment_asset import AgentEnvironmentAssetRecord
from reveng.platform.services.agent_service import AgentService
from reveng.platform.utils import now_utc

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(frozen=True, slots=True)
class AgentEnvironmentThemeDefinition:
    skin_id: str
    display_name: str
    stage_title: str
    chamber_label: str


AGENT_ENVIRONMENT_THEME_DEFINITIONS = (
    AgentEnvironmentThemeDefinition(
        skin_id="skynet",
        display_name="Skynet",
        stage_title="Skynet Chamber Hall",
        chamber_label="Machine Bay",
    ),
)

AGENT_ENVIRONMENT_THEME_BY_ID = {
    definition.skin_id: definition for definition in AGENT_ENVIRONMENT_THEME_DEFINITIONS
}
DEFAULT_AGENT_ENVIRONMENT_SKIN_ID = "skynet"


class AgentEnvironmentAppearanceService:
    ASSET_URL_PREFIX = "/agent-environment-assets"

    _SOURCE_SKINS_ROOT = Path(__file__).resolve().parent / "source_skins"

    def __init__(
        self,
        *,
        agent_service: AgentService | None = None,
        asset_root: Path | None = None,
    ) -> None:
        self._agents = agent_service or AgentService()
        self._asset_root = asset_root or (Path(__file__).resolve().parent / "assets")
        self._asset_root.mkdir(parents=True, exist_ok=True)
        self._rng = random.Random()

    @property
    def asset_root(self) -> Path:
        return self._asset_root

    def list_themes(self) -> list[AgentEnvironmentThemeDefinition]:
        return list(AGENT_ENVIRONMENT_THEME_DEFINITIONS)

    def get_theme(self, skin_id: str) -> AgentEnvironmentThemeDefinition:
        try:
            return AGENT_ENVIRONMENT_THEME_BY_ID[skin_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Agent Environment skin: {skin_id}") from exc

    def sync_bootstrap_shared_backgrounds(self, skin_id: str) -> list[AgentEnvironmentAssetRecord]:
        self.get_theme(skin_id)
        source_dir = self._SOURCE_SKINS_ROOT / skin_id
        bootstrap_files = [
            path for path in sorted(source_dir.glob("*"))
            if path.is_file() and path.suffix.lower() in _IMAGE_EXTENSIONS
        ]
        if not bootstrap_files:
            return self.list_shared_backgrounds(skin_id, sync=False)

        shared_dir = self._shared_pool_directory(skin_id)
        shared_dir.mkdir(parents=True, exist_ok=True)
        for source_path in bootstrap_files:
            existing = self._get_asset_by_source_ref(
                skin_id=skin_id,
                asset_scope="shared_pool",
                source_ref=str(source_path.resolve()),
            )
            target_name = self._bootstrap_stored_filename(source_path.name)
            target_path = shared_dir / target_name
            if existing is not None:
                if not target_path.exists():
                    shutil.copy2(source_path, target_path)
                continue

            shutil.copy2(source_path, target_path)
            self._create_asset(
                skin_id=skin_id,
                asset_scope="shared_pool",
                owner_agent_id=None,
                display_name=source_path.stem,
                original_filename=source_path.name,
                stored_filename=target_name,
                storage_path=self._storage_path_for(target_path),
                source_kind="bootstrap_root",
                source_ref=str(source_path.resolve()),
            )
        return self.list_shared_backgrounds(skin_id, sync=False)

    def list_shared_backgrounds(
        self,
        skin_id: str,
        *,
        sync: bool = True,
    ) -> list[AgentEnvironmentAssetRecord]:
        if sync:
            self.sync_bootstrap_shared_backgrounds(skin_id)
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM agent_environment_assets
                WHERE skin_id = ? AND asset_scope = 'shared_pool' AND is_active = 1
                ORDER BY display_name COLLATE NOCASE ASC, created_at ASC
                """,
                (skin_id,),
            ).fetchall()
        return [AgentEnvironmentAssetRecord.from_row(row) for row in rows]

    def list_agent_custom_backgrounds(
        self,
        agent_id: str,
        skin_id: str,
    ) -> list[AgentEnvironmentAssetRecord]:
        self._agents.get_or_raise(agent_id)
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM agent_environment_assets
                WHERE skin_id = ?
                  AND asset_scope = 'agent_custom'
                  AND owner_agent_id = ?
                  AND is_active = 1
                ORDER BY created_at DESC
                """,
                (skin_id, agent_id),
            ).fetchall()
        return [AgentEnvironmentAssetRecord.from_row(row) for row in rows]

    def get_agent_skin_preference(
        self,
        agent_id: str,
        skin_id: str,
    ) -> AgentEnvironmentAgentSkinPreferenceRecord | None:
        self._agents.get_or_raise(agent_id)
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM agent_environment_agent_skin_preferences
                WHERE agent_id = ? AND skin_id = ?
                """,
                (agent_id, skin_id),
            ).fetchone()
        if row is None:
            return None
        return AgentEnvironmentAgentSkinPreferenceRecord.from_row(row)

    def get_effective_preference(
        self,
        agent_id: str,
        skin_id: str,
    ) -> dict[str, object]:
        preference = self.get_agent_skin_preference(agent_id, skin_id)
        if preference is None:
            return {
                "background_mode": "random",
                "selected_asset_id": None,
                "preference_record": None,
            }
        return {
            "background_mode": preference.background_mode,
            "selected_asset_id": preference.selected_asset_id,
            "preference_record": preference,
        }

    def set_random_background(self, agent_id: str, skin_id: str) -> None:
        self._upsert_preference(
            agent_id=agent_id,
            skin_id=skin_id,
            background_mode="random",
            selected_asset_id=None,
        )

    def set_shared_background(self, agent_id: str, skin_id: str, asset_id: str) -> None:
        asset = self.get_asset_or_raise(asset_id)
        if asset.skin_id != skin_id or asset.asset_scope != "shared_pool":
            raise ValueError("Selected background is not a shared background for this skin.")
        self._upsert_preference(
            agent_id=agent_id,
            skin_id=skin_id,
            background_mode="shared",
            selected_asset_id=asset.id,
        )

    def set_custom_background(self, agent_id: str, skin_id: str, asset_id: str) -> None:
        asset = self.get_asset_or_raise(asset_id)
        if (
            asset.skin_id != skin_id
            or asset.asset_scope != "agent_custom"
            or asset.owner_agent_id != agent_id
        ):
            raise ValueError("Selected background is not a custom background for this agent and skin.")
        self._upsert_preference(
            agent_id=agent_id,
            skin_id=skin_id,
            background_mode="custom",
            selected_asset_id=asset.id,
        )

    def store_shared_background(
        self,
        skin_id: str,
        *,
        filename: str,
        content: bytes,
    ) -> AgentEnvironmentAssetRecord:
        self.get_theme(skin_id)
        target_dir = self._shared_pool_directory(skin_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path, stored_filename = self._store_uploaded_file(
            target_dir=target_dir,
            filename=filename,
            content=content,
        )
        return self._create_asset(
            skin_id=skin_id,
            asset_scope="shared_pool",
            owner_agent_id=None,
            display_name=Path(filename).stem,
            original_filename=filename,
            stored_filename=stored_filename,
            storage_path=self._storage_path_for(target_path),
            source_kind="uploaded",
            source_ref=str(target_path.resolve()),
        )

    def store_custom_background(
        self,
        agent_id: str,
        skin_id: str,
        *,
        filename: str,
        content: bytes,
    ) -> AgentEnvironmentAssetRecord:
        self._agents.get_or_raise(agent_id)
        self.get_theme(skin_id)
        target_dir = self._custom_pool_directory(agent_id, skin_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path, stored_filename = self._store_uploaded_file(
            target_dir=target_dir,
            filename=filename,
            content=content,
        )
        asset = self._create_asset(
            skin_id=skin_id,
            asset_scope="agent_custom",
            owner_agent_id=agent_id,
            display_name=Path(filename).stem,
            original_filename=filename,
            stored_filename=stored_filename,
            storage_path=self._storage_path_for(target_path),
            source_kind="uploaded",
            source_ref=str(target_path.resolve()),
        )
        self.set_custom_background(agent_id, skin_id, asset.id)
        return asset

    def get_asset_or_raise(self, asset_id: str) -> AgentEnvironmentAssetRecord:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM agent_environment_assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Agent Environment asset not found: {asset_id}")
        return AgentEnvironmentAssetRecord.from_row(row)

    def resolve_agent_stage_background(
        self,
        agent_id: str,
        skin_id: str,
    ) -> dict[str, object]:
        self._agents.get_or_raise(agent_id)
        shared_assets = self.list_shared_backgrounds(skin_id)
        custom_assets = self.list_agent_custom_backgrounds(agent_id, skin_id)
        preference = self.get_effective_preference(agent_id, skin_id)
        selected_asset: AgentEnvironmentAssetRecord | None = None
        selected_source = "random"

        if preference["background_mode"] == "shared" and preference["selected_asset_id"]:
            selected_asset = self._find_asset(shared_assets, str(preference["selected_asset_id"]))
            selected_source = "shared"
        elif preference["background_mode"] == "custom" and preference["selected_asset_id"]:
            selected_asset = self._find_asset(custom_assets, str(preference["selected_asset_id"]))
            selected_source = "custom"

        if selected_asset is None and shared_assets:
            selected_asset = self._rng.choice(shared_assets)
            selected_source = "random"

        return {
            "theme": self.get_theme(skin_id),
            "selected_asset": selected_asset,
            "background_url": (
                self.asset_url_for(selected_asset.storage_path)
                if selected_asset is not None
                else None
            ),
            "selection_source": selected_source,
            "shared_pool_count": len(shared_assets),
            "custom_pool_count": len(custom_assets),
            "preference": preference,
        }

    def build_agent_appearance_context(
        self,
        agent_id: str,
        skin_id: str,
    ) -> dict[str, object]:
        stage = self.resolve_agent_stage_background(agent_id, skin_id)
        shared_assets = self.list_shared_backgrounds(skin_id)
        custom_assets = self.list_agent_custom_backgrounds(agent_id, skin_id)
        selected_asset = stage["selected_asset"]
        selected_asset_id = selected_asset.id if selected_asset is not None else None
        return {
            "theme": stage["theme"],
            "current_background": stage,
            "shared_backgrounds": [
                {
                    "asset": asset,
                    "asset_url": self.asset_url_for(asset.storage_path),
                    "is_selected": selected_asset_id == asset.id
                    and stage["selection_source"] == "shared",
                }
                for asset in shared_assets
            ],
            "custom_backgrounds": [
                {
                    "asset": asset,
                    "asset_url": self.asset_url_for(asset.storage_path),
                    "is_selected": selected_asset_id == asset.id
                    and stage["selection_source"] == "custom",
                }
                for asset in custom_assets
            ],
            "background_mode": str(stage["preference"]["background_mode"]),
            "selection_source": stage["selection_source"],
        }

    def asset_url_for(self, storage_path: str) -> str:
        normalized_path = storage_path.replace("\\", "/")
        return f"{self.ASSET_URL_PREFIX}/{quote(normalized_path, safe='/')}"

    def _create_asset(
        self,
        *,
        skin_id: str,
        asset_scope: str,
        owner_agent_id: str | None,
        display_name: str,
        original_filename: str,
        stored_filename: str,
        storage_path: str,
        source_kind: str,
        source_ref: str | None,
    ) -> AgentEnvironmentAssetRecord:
        ts = now_utc()
        asset_id = str(uuid.uuid4())
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO agent_environment_assets (
                    id,
                    environment_id,
                    skin_id,
                    asset_scope,
                    owner_agent_id,
                    display_name,
                    original_filename,
                    stored_filename,
                    storage_path,
                    source_kind,
                    source_ref,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, 'agent_environment', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    asset_id,
                    skin_id,
                    asset_scope,
                    owner_agent_id,
                    display_name,
                    original_filename,
                    stored_filename,
                    storage_path,
                    source_kind,
                    source_ref,
                    ts,
                    ts,
                ),
            )
            conn.commit()
        return self.get_asset_or_raise(asset_id)

    def _upsert_preference(
        self,
        *,
        agent_id: str,
        skin_id: str,
        background_mode: str,
        selected_asset_id: str | None,
    ) -> None:
        self._agents.get_or_raise(agent_id)
        ts = now_utc()
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM agent_environment_agent_skin_preferences
                WHERE agent_id = ? AND skin_id = ?
                """,
                (agent_id, skin_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO agent_environment_agent_skin_preferences (
                        id,
                        agent_id,
                        skin_id,
                        background_mode,
                        selected_asset_id,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        agent_id,
                        skin_id,
                        background_mode,
                        selected_asset_id,
                        ts,
                        ts,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE agent_environment_agent_skin_preferences
                    SET background_mode = ?,
                        selected_asset_id = ?,
                        updated_at = ?
                    WHERE agent_id = ? AND skin_id = ?
                    """,
                    (background_mode, selected_asset_id, ts, agent_id, skin_id),
                )
            conn.commit()

    def _get_asset_by_source_ref(
        self,
        *,
        skin_id: str,
        asset_scope: str,
        source_ref: str,
    ) -> AgentEnvironmentAssetRecord | None:
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM agent_environment_assets
                WHERE skin_id = ? AND asset_scope = ? AND source_ref = ?
                """,
                (skin_id, asset_scope, source_ref),
            ).fetchone()
        if row is None:
            return None
        return AgentEnvironmentAssetRecord.from_row(row)

    def _store_uploaded_file(
        self,
        *,
        target_dir: Path,
        filename: str,
        content: bytes,
    ) -> tuple[Path, str]:
        if not content:
            raise ValueError("Uploaded image is empty.")
        original_name = Path(filename).name
        extension = Path(original_name).suffix.lower()
        if extension not in _IMAGE_EXTENSIONS:
            raise ValueError("Only PNG, JPG, JPEG, and WEBP backgrounds are supported.")
        safe_stem = _SAFE_FILENAME_RE.sub("-", Path(original_name).stem).strip(" .-_") or "background"
        stored_filename = f"{safe_stem}-{uuid.uuid4().hex[:10]}{extension}"
        target_path = target_dir / stored_filename
        target_path.write_bytes(content)
        return target_path, stored_filename

    def _storage_path_for(self, target_path: Path) -> str:
        return target_path.relative_to(self._asset_root).as_posix()

    def _shared_pool_directory(self, skin_id: str) -> Path:
        return self._asset_root / "skins" / skin_id / "shared"

    def _custom_pool_directory(self, agent_id: str, skin_id: str) -> Path:
        return self._asset_root / "skins" / skin_id / "agents" / agent_id

    def _find_asset(
        self,
        assets: list[AgentEnvironmentAssetRecord],
        asset_id: str,
    ) -> AgentEnvironmentAssetRecord | None:
        for asset in assets:
            if asset.id == asset_id:
                return asset
        return None

    def _bootstrap_stored_filename(self, filename: str) -> str:
        return Path(filename).name


__all__ = [
    "DEFAULT_AGENT_ENVIRONMENT_SKIN_ID",
    "AGENT_ENVIRONMENT_THEME_DEFINITIONS",
    "AGENT_ENVIRONMENT_THEME_BY_ID",
    "AgentEnvironmentAppearanceService",
    "AgentEnvironmentThemeDefinition",
]
