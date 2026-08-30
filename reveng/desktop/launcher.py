"""Desktop launcher for RevEng.

Startup sequence:
  1. Resolve stable data directory (~/.reveng/)
  2. Set REVENG_LAUNCHER_ROOT, REVENG_ENV_FILE, REVENG_CAPABILITY_ENV_ASSET_DIR env vars
  3. Find a free OS-assigned port
  4. Start FastAPI/uvicorn in a daemon thread on that port
  5. Wait for backend readiness (HTTP poll)
  6. Open a PyWebView window pointed at the backend
  7. On window close: warn if run is active, save window state, signal shutdown
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

from reveng.desktop.bridge import RevEngBridge
from reveng.desktop.window_state import load_window_state, save_window_state


# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------

def _data_directory() -> Path:
    """Return (and create if needed) the stable writable data directory.

    Standard install: ~/.reveng/
    Portable install: parent directory of the running executable, activated by
    a '.portable' marker file next to the exe.
    """
    exe_parent = Path(sys.executable).parent
    if (exe_parent / ".portable").exists():
        data_dir = exe_parent
    else:
        data_dir = Path.home() / ".reveng"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


# ---------------------------------------------------------------------------
# Host path configuration
# ---------------------------------------------------------------------------

def _configure_host_paths(data_dir: Path) -> None:
    """Set env vars so app.py resolves paths correctly regardless of cwd()."""
    os.environ["REVENG_LAUNCHER_ROOT"] = str(data_dir)

    # Only set REVENG_ENV_FILE if we're not overriding an explicit REVENG_DB
    if not os.environ.get("REVENG_ENV_FILE"):
        os.environ["REVENG_ENV_FILE"] = str(data_dir / ".env")

    # Resolve capability environment assets relative to this file (source tree)
    # or from sys._MEIPASS in a packaged build.
    if not os.environ.get("REVENG_CAPABILITY_ENV_ASSET_DIR"):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            asset_dir = (
                Path(meipass)
                / "reveng"
                / "execution_environment"
                / "capability_environment"
                / "assets"
            )
        else:
            asset_dir = (
                Path(__file__).resolve().parents[2]
                / "execution_environment"
                / "capability_environment"
                / "assets"
            )
        os.environ["REVENG_CAPABILITY_ENV_ASSET_DIR"] = str(asset_dir)


# ---------------------------------------------------------------------------
# Port discovery
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    """Ask the OS for an available port by binding to 0."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Backend lifecycle
# ---------------------------------------------------------------------------

def _start_backend(port: int):
    """Start FastAPI/uvicorn in a daemon thread.  Returns the Server instance."""
    import uvicorn

    config = uvicorn.Config(
        "reveng.platform.web.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True, name="reveng-backend")
    thread.start()
    return server


def _wait_for_backend(port: int, timeout: float = 15.0) -> None:
    """Poll the backend until it returns HTTP 200 or the timeout expires."""
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:
            last_exc = exc
        time.sleep(0.2)
    raise RuntimeError(
        f"RevEng backend did not become ready within {timeout}s "
        f"(last error: {last_exc})"
    )


# ---------------------------------------------------------------------------
# Window closing callback
# ---------------------------------------------------------------------------

def _make_closing_callback(server, data_dir: Path, bridge: RevEngBridge):
    """Return a closure used as the PyWebView 'closing' event handler."""

    def on_closing():
        import webview
        if bridge.has_active_runs():
            windows = webview.windows
            if windows:
                confirmed = windows[0].create_confirmation_dialog(
                    "Analysis in progress",
                    "An analysis run is still active. Close RevEng and stop the run?",
                )
                if not confirmed:
                    return False  # cancel the close

        # Save window state before closing
        import webview
        if webview.windows:
            save_window_state(webview.windows[0], data_dir)

        # Signal uvicorn to shut down
        server.should_exit = True
        return True  # allow the close

    return on_closing


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def launch() -> int:
    """Launch the RevEng desktop application.  Returns an exit code."""
    import webview

    data_dir = _data_directory()
    _configure_host_paths(data_dir)

    db_path = Path(os.environ.get("REVENG_DB", "")) or (data_dir / "reveng_platform.db")

    port = _find_free_port()
    server = _start_backend(port)

    try:
        _wait_for_backend(port)
    except RuntimeError as exc:
        # Show the error inside a minimal window rather than crashing silently
        _show_startup_error(str(exc))
        return 1

    bridge = RevEngBridge(data_dir=data_dir, db_path=data_dir / "reveng_platform.db")

    # Register notification callback so analysis_bridge.py can surface notifications
    from reveng.desktop import notifications
    notifications.register(bridge.notify)

    # Restore saved window geometry
    state = load_window_state(data_dir)
    width = state["width"]
    height = state["height"]
    x = state.get("x")
    y = state.get("y")

    closing_cb = _make_closing_callback(server, data_dir, bridge)

    try:
        win = webview.create_window(
            title="RevEng",
            url=f"http://127.0.0.1:{port}/",  # Phase 4: host shell entry point
            js_api=bridge,
            width=width,
            height=height,
            x=x,
            y=y,
            min_size=(900, 600),
            confirm_close=False,
        )
        webview.start()
    except Exception as exc:
        exc_str = str(exc)
        if "WebView2" in exc_str or "webview" in exc_str.lower():
            _show_webview2_error()
        else:
            raise
        return 1

    return 0


# ---------------------------------------------------------------------------
# Error dialogs
# ---------------------------------------------------------------------------

def _show_startup_error(message: str) -> None:
    """Show a startup failure message via tkinter (available on all platforms)."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("RevEng — Startup Failed", message)
        root.destroy()
    except Exception:
        print(f"RevEng startup error: {message}", file=sys.stderr)


def _show_webview2_error() -> None:
    """Show a WebView2-not-found error with download instructions."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "RevEng — WebView2 Required",
            "RevEng requires Microsoft WebView2 to display its window.\n\n"
            "WebView2 is included with Windows 11 and recent Windows 10 builds.\n\n"
            "If it is missing on your system, install it from:\n"
            "https://developer.microsoft.com/en-us/microsoft-edge/webview2/",
        )
        root.destroy()
    except Exception:
        print(
            "RevEng requires Microsoft WebView2.  "
            "Download from https://developer.microsoft.com/en-us/microsoft-edge/webview2/",
            file=sys.stderr,
        )
