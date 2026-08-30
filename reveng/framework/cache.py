from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class CachePolicy(Protocol):
    def is_ready(
        self,
        path: Path,
        *,
        capability_id: str,
        output_name: str,
        inputs: dict[str, Any],
    ) -> bool:
        ...


class ExistsAndNonEmptyCachePolicy:
    def is_ready(
        self,
        path: Path,
        *,
        capability_id: str,
        output_name: str,
        inputs: dict[str, Any],
    ) -> bool:
        return path.exists() and path.stat().st_size > 0


class NoCachePolicy:
    def is_ready(
        self,
        path: Path,
        *,
        capability_id: str,
        output_name: str,
        inputs: dict[str, Any],
    ) -> bool:
        return False
