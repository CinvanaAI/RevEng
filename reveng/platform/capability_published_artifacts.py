"""
Package-owned published artifact utilities.

Each capability package owns its published artifacts under a package-identified
directory structure. Artifacts are real files — not inline DB content.

Published artifact directory (package-owned):
    reveng/capabilities/packages/<safe_id>/published/
        python/implementation.py     — Python artifact (importable)
        json/snapshot.json           — JSON artifact (machine-readable snapshot)
        text/summary.txt             — Text artifact (human-readable summary)

<safe_id> = capability_id.replace('.', '_').replace('-', '_')

This module is the single source of truth for path layout and artifact writes.
Callers (e.g. capability_catalog_service.install_published_draft_items) use
these functions; they do not construct paths themselves.

Cache invalidation
------------------
After writing a Python artifact, call invalidate_published_python_cache() so
the next import re-reads the updated file.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PACKAGES_ROOT = Path(__file__).parent.parent / "capabilities" / "packages"


def _safe_id(capability_id: str) -> str:
    return capability_id.replace(".", "_").replace("-", "_")


def published_artifact_dir(capability_id: str) -> Path:
    """Return the package-owned published root directory for *capability_id*."""
    return _PACKAGES_ROOT / _safe_id(capability_id) / "published"


def published_python_path(capability_id: str) -> Path:
    """Return the path to the package-owned Python artifact."""
    return published_artifact_dir(capability_id) / "python" / "implementation.py"


def published_json_path(capability_id: str) -> Path:
    """Return the path to the package-owned JSON artifact."""
    return published_artifact_dir(capability_id) / "json" / "snapshot.json"


def published_text_path(capability_id: str) -> Path:
    """Return the path to the package-owned text artifact."""
    return published_artifact_dir(capability_id) / "text" / "summary.txt"


def write_published_python(capability_id: str, code_block: str) -> Path:
    """
    Write the Python artifact for *capability_id*.

    Creates the package directory, __init__.py markers for Python's import
    system, and writes code_block as implementation.py.

    Returns the path to the written file.
    """
    safe = _safe_id(capability_id)
    pkg_root = _PACKAGES_ROOT / safe
    published_dir = pkg_root / "published"
    python_dir = published_dir / "python"
    python_dir.mkdir(parents=True, exist_ok=True)

    # __init__.py markers for the import chain:
    #   reveng.capabilities.packages
    #   reveng.capabilities.packages.<safe_id>
    #   reveng.capabilities.packages.<safe_id>.published
    #   reveng.capabilities.packages.<safe_id>.published.python
    for marker_dir in [
        _PACKAGES_ROOT,
        pkg_root,
        published_dir,
        python_dir,
    ]:
        init = marker_dir / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")

    impl_file = python_dir / "implementation.py"
    impl_file.write_text(code_block, encoding="utf-8")
    return impl_file


def write_published_json(capability_id: str, json_content: str) -> Path:
    """
    Write the JSON artifact for *capability_id*.

    Returns the path to the written file.
    """
    json_dir = published_artifact_dir(capability_id) / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = json_dir / "snapshot.json"
    snapshot_file.write_text(json_content, encoding="utf-8")
    return snapshot_file


def write_published_text(capability_id: str, text_content: str) -> Path:
    """
    Write the text artifact for *capability_id*.

    Returns the path to the written file.
    """
    text_dir = published_artifact_dir(capability_id) / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    summary_file = text_dir / "summary.txt"
    summary_file.write_text(text_content, encoding="utf-8")
    return summary_file


def invalidate_published_python_cache(capability_id: str) -> None:
    """
    Evict the package-owned Python module from sys.modules so the next
    import re-reads the updated implementation.py.

    Call this after write_published_python().
    """
    safe = _safe_id(capability_id)
    module_path = f"reveng.capabilities.packages.{safe}.published.python.implementation"
    prefixes = [
        module_path,
        f"reveng.capabilities.packages.{safe}.published.python",
        f"reveng.capabilities.packages.{safe}.published",
        f"reveng.capabilities.packages.{safe}",
    ]
    for key in list(sys.modules):
        if any(key == p or key.startswith(p + ".") for p in prefixes):
            del sys.modules[key]


def build_text_summary(snapshot: dict) -> str:
    """
    Build a human-readable text summary from a capability snapshot dict.

    Used when generating a text_summary published form.
    """
    lines = [
        f"Capability: {snapshot.get('capability_id', '(unknown)')}",
        f"Display Name: {snapshot.get('display_name', '')}",
        f"Type: {snapshot.get('capability_type', 'function')}",
        f"Version: {snapshot.get('version', '1')}",
        f"Pack: {snapshot.get('pack_id', '')}",
        f"Execution Source: {snapshot.get('execution_source', 'binding_ref')}",
        f"Entrypoint: {snapshot.get('entrypoint', 'run')}",
        "",
        "Description:",
        snapshot.get("description", ""),
        "",
    ]
    contract = snapshot.get("contract", {})
    inputs = contract.get("inputs", [])
    output = contract.get("output", [])
    constraints = contract.get("constraints", [])
    if inputs:
        lines.append("Inputs:")
        for inp in inputs:
            lines.append(f"  - {inp}")
        lines.append("")
    if output:
        lines.append("Output:")
        for out in output:
            lines.append(f"  - {out}")
        lines.append("")
    if constraints:
        lines.append("Constraints:")
        for c in constraints:
            lines.append(f"  - {c}")
        lines.append("")
    tags = snapshot.get("tags", [])
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")
    published_forms = snapshot.get("published_forms", [])
    if published_forms:
        lines.append(f"Published Forms: {', '.join(published_forms)}")
    return "\n".join(lines)


__all__ = [
    "published_artifact_dir",
    "published_python_path",
    "published_json_path",
    "published_text_path",
    "write_published_python",
    "write_published_json",
    "write_published_text",
    "invalidate_published_python_cache",
    "build_text_summary",
]
