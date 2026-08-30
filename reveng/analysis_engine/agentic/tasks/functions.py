"""Shared helper utilities for all Task Agent modules.

These are pure functions with no side effects, importable from any task agent.
"""
from __future__ import annotations

import hashlib
from typing import Any

from reveng.analysis_engine.meaning.derivation import DerivationBasis, DerivationRecord
from reveng.analysis_engine.meaning.layers import LayerID


# ---------------------------------------------------------------------------
# Evidence ref encoding / decoding
# ---------------------------------------------------------------------------

_SEP = "::"


def _build_evidence_ref(
    file_path: str,
    scope: str,
    lineno: int | None,
    detail: str,
) -> str:
    """Encode an evidence ref as 'file_path::scope::lineno::detail'."""
    return _SEP.join([file_path, scope, str(lineno) if lineno is not None else "", detail])


def _parse_evidence_ref(ref: str) -> dict[str, str | int | None]:
    """Decode an evidence ref into its components."""
    parts = ref.split(_SEP, 3)
    while len(parts) < 4:
        parts.append("")
    file_path, scope, lineno_str, detail = parts
    lineno: int | None = None
    if lineno_str:
        try:
            lineno = int(lineno_str)
        except ValueError:
            pass
    return {"file_path": file_path, "scope": scope, "lineno": lineno, "detail": detail}


# ---------------------------------------------------------------------------
# Stable ID generation
# ---------------------------------------------------------------------------

def _generate_id(prefix: str, *parts: str) -> str:
    """Generate a stable 12-character ID from prefix + parts."""
    raw = ":".join([prefix] + list(parts))
    return prefix + "_" + hashlib.sha256(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Function scope lookup
# ---------------------------------------------------------------------------

def _resolve_function_scope(enriched_file: dict[str, Any], scope_name: str) -> dict[str, Any] | None:
    """Find the first defined_symbol in an enriched file record matching scope_name."""
    for symbol in enriched_file.get("defined_symbols", []):
        name = symbol.get("name", "")
        # Scope may be "ClassName.method_name", "module > function:name", or plain "function_name"
        if name == scope_name or scope_name.endswith("." + name) or scope_name.endswith(":" + name):
            return symbol
    return None


# ---------------------------------------------------------------------------
# Derivation record factory
# ---------------------------------------------------------------------------

def _make_derivation(
    basis: DerivationBasis,
    source_layer: LayerID | None = None,
    source_ids: list[str] | None = None,
    notes: str = "",
    phase1_approximation: bool = False,
) -> DerivationRecord:
    return DerivationRecord(
        basis=basis,
        source_layer=source_layer.value if source_layer is not None else None,
        source_ids=source_ids or [],
        notes=notes,
        phase1_approximation=phase1_approximation,
    )


# ---------------------------------------------------------------------------
# File lookup helpers
# ---------------------------------------------------------------------------

def _build_file_index(enriched: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a {relative_path: file_record} index from an enriched breakdown."""
    return {fr.get("path", ""): fr for fr in enriched.get("files", [])}


def _calls_in_file(file_record: dict[str, Any]) -> list[dict[str, Any]]:
    return file_record.get("calls", [])


def _side_effects_text(file_record: dict[str, Any]) -> list[str]:
    return file_record.get("observed_side_effects", [])


def _decorators_in_file(file_record: dict[str, Any]) -> list[dict[str, Any]]:
    return file_record.get("decorators", [])


def _classes_in_file(file_record: dict[str, Any]) -> list[dict[str, Any]]:
    return file_record.get("classes", [])


# Names that are Python builtins — not meaningful as callee signals.
_BUILTIN_NAMES: frozenset[str] = frozenset((
    "print", "len", "str", "int", "float", "bool", "list", "dict", "set",
    "tuple", "range", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "any", "all", "sum", "min", "max", "abs", "round", "isinstance", "hasattr",
    "getattr", "setattr", "type", "repr", "hash", "id", "iter", "next",
    "open",
))


def _body_has_nontrivial_content(file_record: dict[str, Any], scope: str) -> bool:
    """Return True if the function body contains non-trivial complexity signals.

    Signals: any raises, any own-scope assignments, multiple return statements,
    or any control-flow constructs (if/for/while/try/with) in the function's scope.
    Used by Phase 10 to distinguish thin_wrapper from pure_wrapper.
    """
    basename = scope.split(":")[-1] if ":" in scope else scope

    def _matches(enc: str) -> bool:
        return (enc == scope or enc == basename
                or enc.endswith(":" + basename) or enc.endswith("." + basename))

    for rec in file_record.get("raises", []):
        if _matches(rec.get("enclosing_scope", "")):
            return True

    for rec in file_record.get("assignments", []):
        if _matches(rec.get("enclosing_scope", "")):
            return True

    return_count = sum(
        1 for rec in file_record.get("returns", [])
        if _matches(rec.get("enclosing_scope", ""))
    )
    if return_count > 1:
        return True

    for rec in file_record.get("control_flow", []):
        if _matches(rec.get("enclosing_scope", "")):
            return True

    return False


def _get_callee_names(file_index: dict[str, Any], file_path: str, scope: str) -> set[str]:
    """Return distinct non-builtin callee names called from *scope* in *file_path*."""
    file_record = file_index.get(file_path, {})
    basename = scope.split(":")[-1] if ":" in scope else scope
    callees: set[str] = set()
    for call in file_record.get("calls", []):
        enc = call.get("enclosing_scope", "")
        if not (enc == scope or enc == basename
                or enc.endswith(":" + basename) or enc.endswith("." + basename)):
            continue
        called = call.get("called_name", "")
        if called and called not in _BUILTIN_NAMES:
            callees.add(called)
    return callees


def _count_distinct_callees(file_index: dict[str, Any], file_path: str, scope: str) -> int:
    """Count distinct non-builtin callee names made from *scope* in *file_path*."""
    return len(_get_callee_names(file_index, file_path, scope))


def _scope_display(scope: str) -> str:
    """Convert a qualified scope to a readable display name.

    'module > class:Foo > method:bar'  → 'Foo.bar'
    'module > function:run'            → 'run'
    'run'                              → 'run'
    """
    parts = [p.strip() for p in scope.split(">")]
    components: list[str] = []
    for p in parts:
        if ":" in p:
            kind, _, name = p.partition(":")
            if kind.strip() in ("class", "method", "function", "async_function"):
                components.append(name.strip())
    return ".".join(components) if components else scope


def _is_test_file(file_path: str) -> bool:
    """Return True if file_path looks like a test file by naming convention."""
    parts = file_path.replace("\\", "/").split("/")
    name = parts[-1] if parts else ""
    return (
        name.startswith("test_") or name.endswith("_test.py")
        or any(p in ("tests", "test", "testing", "spec", "__tests__") for p in parts[:-1])
    )
