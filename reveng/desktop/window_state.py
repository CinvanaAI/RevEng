"""Window geometry persistence for the RevEng desktop shell."""
from __future__ import annotations

import json
from pathlib import Path

_STATE_FILENAME = "window_state.json"
_DEFAULTS: dict = {"width": 1280, "height": 900, "x": None, "y": None}


def load_window_state(data_dir: Path) -> dict:
    """Return saved window geometry, or defaults if the file is absent or corrupt."""
    path = data_dir / _STATE_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {
            "width": int(raw.get("width", _DEFAULTS["width"])),
            "height": int(raw.get("height", _DEFAULTS["height"])),
            "x": raw.get("x"),
            "y": raw.get("y"),
        }
    except Exception:
        return dict(_DEFAULTS)


def save_window_state(window, data_dir: Path) -> None:
    """Write the current window geometry to disk."""
    path = data_dir / _STATE_FILENAME
    try:
        state = {"width": window.width, "height": window.height, "x": window.x, "y": window.y}
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass  # non-fatal: state persistence is best-effort
