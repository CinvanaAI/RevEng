"""
Storage Substrate artifact utilities.

Low-level helpers for reading durable artifacts from disk.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def artifact_ready(path: Path) -> bool:
    """Return True if a durable artifact exists and is non-empty."""
    return path.exists() and path.stat().st_size > 0


def load_json(path: Path) -> Any:
    """Load a JSON artifact from disk."""
    return json.loads(path.read_text(encoding="utf-8"))
