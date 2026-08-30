"""
Capability Environment skin packages owned by the environment domain.

These packages describe a shared six-action hub surface rendered through
theme-specific art, labels, and hotspot regions. Backend action wiring is
deliberately out of scope here; the packages only establish environment-owned
presentation structure for the Capability Environment object.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


CAPABILITY_ENVIRONMENT_CANONICAL_ACTION_IDS = (
    "create_draft",
    "inventory_wall",
    "workbench",
    "ledger",
    "dispatch_bench",
    "return",
)

CAPABILITY_ENVIRONMENT_ASSET_URL_PREFIX = "/environment-assets/capability_environment/skins"


@dataclass(frozen=True, slots=True)
class CapabilityEnvironmentHotspot:
    action_id: str
    display_label: str
    left_pct: float
    top_pct: float
    width_pct: float
    height_pct: float

    @property
    def bounds_style(self) -> str:
        return (
            f"left:{self.left_pct:.2f}%;"
            f"top:{self.top_pct:.2f}%;"
            f"width:{self.width_pct:.2f}%;"
            f"height:{self.height_pct:.2f}%;"
        )


@dataclass(frozen=True, slots=True)
class CapabilityEnvironmentSkinPackage:
    skin_id: str
    tone: str
    domain_label: str
    surface_title: str
    surface_image_url: str
    hotspots: tuple[CapabilityEnvironmentHotspot, ...]


def _skin_asset_url(filename: str) -> str:
    return f"{CAPABILITY_ENVIRONMENT_ASSET_URL_PREFIX}/{filename}"


CAPABILITY_ENVIRONMENT_SKIN_PACKAGES = (
    CapabilityEnvironmentSkinPackage(
        skin_id="capability_workshop",
        tone="ember",
        domain_label="Execution Environment Domain",
        surface_title="Capability Workshop",
        surface_image_url=_skin_asset_url("capability_workshop.png"),
        hotspots=(
            CapabilityEnvironmentHotspot("create_draft", "Forge New Draft", 1.95, 25.98, 21.68, 11.23),
            CapabilityEnvironmentHotspot("inventory_wall", "Inventory Wall", 68.42, 17.09, 19.01, 10.25),
            CapabilityEnvironmentHotspot("workbench", "Draft Table", 67.74, 53.71, 18.49, 11.52),
            CapabilityEnvironmentHotspot("ledger", "Ledger", 20.05, 71.98, 21.81, 12.89),
            CapabilityEnvironmentHotspot("dispatch_bench", "Dispatch Bench", 80.21, 82.91, 18.16, 13.57),
            CapabilityEnvironmentHotspot("return", "Return to Agent", 1.17, 91.02, 17.45, 7.81),
        ),
    ),
    CapabilityEnvironmentSkinPackage(
        skin_id="arcane_archives",
        tone="archive",
        domain_label="Arcane Environment",
        surface_title="Arcane Archives",
        surface_image_url=_skin_asset_url("arcane_archives.png"),
        hotspots=(
            CapabilityEnvironmentHotspot("create_draft", "Scribe New Manuscript", 2.80, 26.07, 25.59, 10.94),
            CapabilityEnvironmentHotspot("inventory_wall", "Reliquary Vault", 73.50, 21.29, 18.62, 11.52),
            CapabilityEnvironmentHotspot("workbench", "Scriptorium", 51.49, 57.81, 24.28, 13.28),
            CapabilityEnvironmentHotspot("ledger", "Codex of Records", 14.26, 67.38, 30.27, 13.67),
            CapabilityEnvironmentHotspot("dispatch_bench", "Dispatch Desk", 69.86, 87.11, 23.37, 11.91),
            CapabilityEnvironmentHotspot("return", "Return to Archivist", 1.17, 89.94, 18.29, 8.79),
        ),
    ),
    CapabilityEnvironmentSkinPackage(
        skin_id="skynet",
        tone="skynet",
        domain_label="System Node",
        surface_title="SKYNET",
        surface_image_url=_skin_asset_url("skynet.png"),
        hotspots=(
            CapabilityEnvironmentHotspot("create_draft", "Initialize New Loadout", 1.43, 20.70, 27.93, 12.79),
            CapabilityEnvironmentHotspot("inventory_wall", "External Terminals", 65.49, 15.53, 31.64, 10.94),
            CapabilityEnvironmentHotspot("workbench", "Ordnance Bay", 11.46, 64.55, 26.82, 13.09),
            CapabilityEnvironmentHotspot("ledger", "Ledger", 38.02, 65.23, 24.87, 12.01),
            CapabilityEnvironmentHotspot("dispatch_bench", "Dispatch Core", 63.02, 64.75, 32.29, 12.79),
            CapabilityEnvironmentHotspot("return", "Return to Command Hub", 71.22, 80.76, 26.30, 10.06),
        ),
    ),
    CapabilityEnvironmentSkinPackage(
        skin_id="command_deck",
        tone="command",
        domain_label="Command Deck",
        surface_title="Initialize Protocol",
        surface_image_url=_skin_asset_url("command_deck.png"),
        hotspots=(
            CapabilityEnvironmentHotspot("create_draft", "Initialize Protocol", 5.60, 42.19, 18.10, 17.97),
            CapabilityEnvironmentHotspot("inventory_wall", "Deployed Inventory", 72.33, 41.80, 22.98, 22.17),
            CapabilityEnvironmentHotspot("workbench", "Active Systems Bay", 14.71, 65.53, 20.64, 19.92),
            CapabilityEnvironmentHotspot("ledger", "External Modules", 38.48, 66.11, 22.00, 19.14),
            CapabilityEnvironmentHotspot("dispatch_bench", "Deployment Vector", 63.93, 65.92, 20.90, 16.11),
            CapabilityEnvironmentHotspot("return", "Return to Command Deck", 72.59, 90.14, 24.22, 5.96),
        ),
    ),
    CapabilityEnvironmentSkinPackage(
        skin_id="weapons_cache",
        tone="bunker",
        domain_label="Military Facility",
        surface_title="Weapons Cache",
        surface_image_url=_skin_asset_url("weapons_cache.png"),
        hotspots=(
            CapabilityEnvironmentHotspot("create_draft", "Assemble New Loadout", 2.21, 21.68, 25.85, 11.82),
            CapabilityEnvironmentHotspot("inventory_wall", "Armory Racks", 73.83, 21.97, 20.96, 11.43),
            CapabilityEnvironmentHotspot("workbench", "Workbench", 14.19, 63.77, 24.54, 13.57),
            CapabilityEnvironmentHotspot("ledger", "Audit Ledger", 39.06, 63.77, 24.22, 13.57),
            CapabilityEnvironmentHotspot("dispatch_bench", "Deployment", 63.74, 63.77, 22.92, 13.57),
            CapabilityEnvironmentHotspot("return", "Return to Command", 1.56, 88.38, 19.34, 9.08),
        ),
    ),
    CapabilityEnvironmentSkinPackage(
        skin_id="cold_storage",
        tone="cold",
        domain_label="Cold Storage",
        surface_title="Cannibal Processing Facility",
        surface_image_url=_skin_asset_url("cold_storage.png"),
        hotspots=(
            CapabilityEnvironmentHotspot("create_draft", "Prepare New Cut", 2.15, 55.08, 24.80, 11.23),
            CapabilityEnvironmentHotspot("inventory_wall", "Cold Storage", 80.79, 2.73, 16.47, 10.74),
            CapabilityEnvironmentHotspot("workbench", "Processing Table", 51.56, 42.19, 29.69, 15.43),
            CapabilityEnvironmentHotspot("ledger", "Cannibal's Notes", 38.41, 81.45, 19.73, 7.32),
            CapabilityEnvironmentHotspot("dispatch_bench", "Packaging & Shipment", 79.04, 80.27, 17.45, 6.25),
            CapabilityEnvironmentHotspot("return", "Leave Facility", 76.76, 89.65, 20.77, 7.91),
        ),
    ),
)

CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID = {
    package.skin_id: package for package in CAPABILITY_ENVIRONMENT_SKIN_PACKAGES
}


def choose_random_capability_environment_skin_package(
    *,
    rng: random.Random | None = None,
) -> CapabilityEnvironmentSkinPackage:
    chooser = rng if rng is not None else random
    return chooser.choice(CAPABILITY_ENVIRONMENT_SKIN_PACKAGES)


def _validate_skin_packages() -> None:
    canonical_action_ids = set(CAPABILITY_ENVIRONMENT_CANONICAL_ACTION_IDS)
    if len(CAPABILITY_ENVIRONMENT_SKIN_PACKAGES) != 6:
        raise ValueError("Capability Environment requires exactly 6 skin packages in this pass.")

    seen_skin_ids: set[str] = set()
    for package in CAPABILITY_ENVIRONMENT_SKIN_PACKAGES:
        if package.skin_id in seen_skin_ids:
            raise ValueError(f"Duplicate Capability Environment skin id: {package.skin_id}")
        seen_skin_ids.add(package.skin_id)

        hotspot_action_ids = [hotspot.action_id for hotspot in package.hotspots]
        if len(package.hotspots) != 6:
            raise ValueError(f"{package.skin_id} must expose exactly 6 hotspots.")
        if set(hotspot_action_ids) != canonical_action_ids:
            raise ValueError(
                f"{package.skin_id} hotspots must match canonical action ids: "
                f"{CAPABILITY_ENVIRONMENT_CANONICAL_ACTION_IDS}"
            )
        if len(hotspot_action_ids) != len(set(hotspot_action_ids)):
            raise ValueError(f"{package.skin_id} cannot repeat canonical action ids.")


_validate_skin_packages()


__all__ = [
    "CAPABILITY_ENVIRONMENT_ASSET_URL_PREFIX",
    "CAPABILITY_ENVIRONMENT_CANONICAL_ACTION_IDS",
    "CAPABILITY_ENVIRONMENT_SKIN_PACKAGES",
    "CAPABILITY_ENVIRONMENT_SKIN_PACKAGE_BY_ID",
    "CapabilityEnvironmentHotspot",
    "CapabilityEnvironmentSkinPackage",
    "choose_random_capability_environment_skin_package",
]
