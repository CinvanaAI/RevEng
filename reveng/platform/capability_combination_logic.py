"""Platform-owned combination logic helpers for installed capabilities."""
from __future__ import annotations

from typing import Any, Callable


def combination_logic_merge(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload.get("merged", {}))


def combination_logic_first(payload: dict[str, Any]) -> dict[str, Any]:
    order = payload.get("execution_order", ())
    per_component = payload.get("per_component", {})
    if not order:
        return {}
    return dict(per_component.get(order[0], {}))


def combination_logic_collect(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload.get("per_component", {}))


COMBINATION_LOGIC_CALLABLES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "merge": combination_logic_merge,
    "first": combination_logic_first,
    "collect": combination_logic_collect,
}

COMBINATION_LOGIC_BINDING_REFS: dict[str, str] = {
    kind: f"{callable_obj.__module__}:{callable_obj.__qualname__}"
    for kind, callable_obj in COMBINATION_LOGIC_CALLABLES.items()
}


def resolve_combination_logic(kind: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    try:
        return COMBINATION_LOGIC_CALLABLES[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported combination_logic_kind: {kind!r}") from exc


def binding_ref_for_combination_logic_kind(kind: str) -> str:
    try:
        return COMBINATION_LOGIC_BINDING_REFS[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported combination_logic_kind: {kind!r}") from exc


__all__ = [
    "COMBINATION_LOGIC_BINDING_REFS",
    "COMBINATION_LOGIC_CALLABLES",
    "binding_ref_for_combination_logic_kind",
    "resolve_combination_logic",
]
