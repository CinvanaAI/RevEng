"""Python↔JS bridge exposed to the webview as window.pywebview.api.

Phase 1: OS operations only.
Phase 4 will add: get_initial_state(), navigate(), push_event().
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class RevEngBridge:
    """All public methods are callable from JavaScript as window.pywebview.api.<method>()."""

    def __init__(self, data_dir: Path, db_path: Path) -> None:
        self._data_dir = data_dir
        self._db_path = db_path

    # ------------------------------------------------------------------
    # OS file picker operations
    # ------------------------------------------------------------------

    def pick_directory(self) -> str | None:
        """Open a native OS folder picker.  Returns the selected path or None."""
        import webview
        windows = webview.windows
        if not windows:
            return None
        result = windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            return result[0]
        return None

    def pick_file(self, file_types: list | None = None) -> str | None:
        """Open a native OS file picker.  Returns the selected path or None.

        file_types: list of strings like 'Images (*.png;*.jpg)' — passed to
        the dialog.  Pass an empty list or None for all files.
        """
        import webview
        windows = webview.windows
        if not windows:
            return None
        ft = tuple(file_types) if file_types else ()
        result = windows[0].create_file_dialog(webview.OPEN_DIALOG, file_types=ft)
        if result:
            return result[0]
        return None

    # ------------------------------------------------------------------
    # OS notification
    # ------------------------------------------------------------------

    def notify(self, title: str, message: str) -> None:
        """Show an OS native notification toast if supported."""
        try:
            # plyer is optional; skip silently if unavailable
            from plyer import notification as _notif  # type: ignore[import]
            _notif.notify(title=title, message=message, app_name="RevEng", timeout=5)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Host diagnostics
    # ------------------------------------------------------------------

    def has_active_runs(self) -> bool:
        """Return True if any analysis run is currently in 'running' status.

        Reads the DB directly — does not go through any service — to avoid
        coupling the bridge to the platform service layer.
        """
        if not self._db_path.exists():
            return False
        try:
            con = sqlite3.connect(str(self._db_path), timeout=2)
            try:
                cur = con.execute(
                    "SELECT 1 FROM analysis_runs WHERE status = 'running' LIMIT 1"
                )
                return cur.fetchone() is not None
            finally:
                con.close()
        except Exception:
            return False

    def get_platform_info(self) -> dict[str, Any]:
        """Return diagnostic info about the current install."""
        import sys
        return {
            "data_dir": str(self._data_dir),
            "db_path": str(self._db_path),
            "version": "desktop",
            "mode": "desktop",
            "python": sys.version,
        }

    # ------------------------------------------------------------------
    # Host navigation (Phase 4)
    # ------------------------------------------------------------------

    def get_initial_state(self) -> dict[str, Any]:
        """Return the starting environment and context for the host shell."""
        return {"environment": "capability_environment", "context": {}}

    def navigate(
        self,
        environment: str,
        surface: str | None = None,
        context: dict | None = None,
    ) -> None:
        """Record a host-level navigation.  Called from Python to drive the host."""
        pass  # Implemented per-domain when environment modules exist

    def push_event(self, event_type: str, payload: dict | None = None) -> None:
        """Push a system event to the active environment module."""
        import json
        import webview
        if webview.windows:
            payload_json = json.dumps(payload or {})
            event_json = json.dumps(event_type)
            webview.windows[0].evaluate_js(
                f"window.__revengHost && window.__revengHost.pushEvent({event_json}, {payload_json})"
            )
