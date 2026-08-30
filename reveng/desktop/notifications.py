"""Module-level notification callback registration.

The desktop launcher registers a callback here at startup.
Platform services (e.g. analysis_bridge) call send() without importing
anything from reveng/desktop/ directly — this module is the one-way seam.

In server.py (dev/CLI) mode, register() is never called, so send() is a no-op.
"""
from __future__ import annotations

from typing import Callable

_notify_fn: Callable[[str, str], None] | None = None


def register(fn: Callable[[str, str], None]) -> None:
    """Register the notification callback.  Called once at launcher startup."""
    global _notify_fn
    _notify_fn = fn


def send(title: str, message: str) -> None:
    """Send a notification.  No-op if no callback has been registered."""
    if _notify_fn is not None:
        try:
            _notify_fn(title, message)
        except Exception:
            pass  # notifications are best-effort; never raise
