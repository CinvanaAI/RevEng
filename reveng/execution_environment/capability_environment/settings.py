"""Capability Environment settings owned by the execution-environment domain."""
from __future__ import annotations

from dataclasses import dataclass

from reveng.execution_environment.capability_environment.skins import (
    CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID,
)
from reveng.platform.utils import now_utc
from reveng.storage.db_connection import get_db

DEFAULT_CAPABILITY_ENVIRONMENT_SETTINGS_ID = "default"
DEFAULT_CAPABILITY_ENVIRONMENT_SKIN_ID = "random"


@dataclass(frozen=True, slots=True)
class CapabilityEnvironmentSettings:
    settings_id: str
    enable_skins: bool
    selected_skin_id: str
    updated_at: str

    @property
    def selected_skin_label(self) -> str:
        if self.selected_skin_id == DEFAULT_CAPABILITY_ENVIRONMENT_SKIN_ID:
            return "Random"
        package = CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID.get(self.selected_skin_id)
        return package.surface_title if package is not None else self.selected_skin_id

    @property
    def manifestation_label(self) -> str:
        return "Skins Enabled" if self.enable_skins else "Neutral Environment"


class CapabilityEnvironmentSettingsService:
    """Storage-backed settings authority for Capability Environment manifestation."""

    def get_settings(self) -> CapabilityEnvironmentSettings:
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM capability_environment_settings
                WHERE settings_id = ?
                """,
                (DEFAULT_CAPABILITY_ENVIRONMENT_SETTINGS_ID,),
            ).fetchone()
            if row is None:
                ts = now_utc()
                conn.execute(
                    """
                    INSERT INTO capability_environment_settings (
                        settings_id,
                        enable_skins,
                        selected_skin_id,
                        updated_at
                    )
                    VALUES (?, 0, ?, ?)
                    """,
                    (
                        DEFAULT_CAPABILITY_ENVIRONMENT_SETTINGS_ID,
                        DEFAULT_CAPABILITY_ENVIRONMENT_SKIN_ID,
                        ts,
                    ),
                )
                conn.commit()
                row = conn.execute(
                    """
                    SELECT *
                    FROM capability_environment_settings
                    WHERE settings_id = ?
                    """,
                    (DEFAULT_CAPABILITY_ENVIRONMENT_SETTINGS_ID,),
                ).fetchone()
        return CapabilityEnvironmentSettings(
            settings_id=row["settings_id"],
            enable_skins=bool(row["enable_skins"]),
            selected_skin_id=row["selected_skin_id"],
            updated_at=row["updated_at"],
        )

    def update_settings(
        self,
        *,
        enable_skins: bool,
        selected_skin_id: str,
    ) -> CapabilityEnvironmentSettings:
        normalized_skin_id = (selected_skin_id or DEFAULT_CAPABILITY_ENVIRONMENT_SKIN_ID).strip()
        if normalized_skin_id != DEFAULT_CAPABILITY_ENVIRONMENT_SKIN_ID:
            if normalized_skin_id not in CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID:
                raise ValueError(f"Unknown Capability Environment skin: {selected_skin_id!r}")

        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO capability_environment_settings (
                    settings_id,
                    enable_skins,
                    selected_skin_id,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(settings_id) DO UPDATE SET
                    enable_skins=excluded.enable_skins,
                    selected_skin_id=excluded.selected_skin_id,
                    updated_at=excluded.updated_at
                """,
                (
                    DEFAULT_CAPABILITY_ENVIRONMENT_SETTINGS_ID,
                    int(enable_skins),
                    normalized_skin_id,
                    ts,
                ),
            )
            conn.commit()
        return self.get_settings()

    def list_skin_options(self) -> list[dict[str, str]]:
        options = [
            {
                "value": DEFAULT_CAPABILITY_ENVIRONMENT_SKIN_ID,
                "label": "Random",
            }
        ]
        for package in CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID.values():
            options.append(
                {
                    "value": package.skin_id,
                    "label": package.surface_title,
                }
            )
        return options


__all__ = [
    "CapabilityEnvironmentSettings",
    "CapabilityEnvironmentSettingsService",
    "DEFAULT_CAPABILITY_ENVIRONMENT_SETTINGS_ID",
    "DEFAULT_CAPABILITY_ENVIRONMENT_SKIN_ID",
]
