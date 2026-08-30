"""Capability Environment application service and station registry."""

from .service import CapabilityEnvironmentService
from .settings import (
    CapabilityEnvironmentSettings,
    CapabilityEnvironmentSettingsService,
)
from .skins import (
    CAPABILITY_ENVIRONMENT_ASSET_URL_PREFIX,
    CAPABILITY_ENVIRONMENT_CANONICAL_ACTION_IDS,
    CAPABILITY_ENVIRONMENT_SKIN_PACKAGES,
    CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID,
    CapabilityEnvironmentHotspot,
    CapabilityEnvironmentSkinPackage,
    choose_random_capability_environment_skin_package,
)
from .stations import (
    CAPABILITY_ENVIRONMENT_OBJECT,
    CAPABILITY_ENVIRONMENT_STATIONS,
    CAPABILITY_ENVIRONMENT_STATION_BY_ACTION,
    CAPABILITY_ENVIRONMENT_STATION_BY_ROUTE_SEGMENT,
    CAPABILITY_ENVIRONMENT_STATION_ALIASES,
    resolve_capability_environment_station_action,
)

__all__ = [
    "CapabilityEnvironmentService",
    "CapabilityEnvironmentSettings",
    "CapabilityEnvironmentSettingsService",
    "CAPABILITY_ENVIRONMENT_ASSET_URL_PREFIX",
    "CAPABILITY_ENVIRONMENT_CANONICAL_ACTION_IDS",
    "CAPABILITY_ENVIRONMENT_OBJECT",
    "CAPABILITY_ENVIRONMENT_SKIN_PACKAGES",
    "CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID",
    "CAPABILITY_ENVIRONMENT_STATIONS",
    "CAPABILITY_ENVIRONMENT_STATION_BY_ACTION",
    "CAPABILITY_ENVIRONMENT_STATION_BY_ROUTE_SEGMENT",
    "CAPABILITY_ENVIRONMENT_STATION_ALIASES",
    "CapabilityEnvironmentHotspot",
    "CapabilityEnvironmentSkinPackage",
    "choose_random_capability_environment_skin_package",
    "resolve_capability_environment_station_action",
]
