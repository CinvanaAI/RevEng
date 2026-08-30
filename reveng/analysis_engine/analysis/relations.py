from __future__ import annotations

import builtins
import sys
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any


@dataclass
class NodeRecord:
    node_id: str
    node_type: str
    file_path: str
    name: str
    scope: str
    lineno: int | None
    end_lineno: int | None


@dataclass
class EdgeRecord:
    edge_type: str
    source_id: str
    target_id: str
    evidence: str
    lineno: int | None
    end_lineno: int | None


BUILTIN_NAMES = set(dir(builtins))
STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", set()))

COMMON_CONTAINER_METHODS = {
    "append",
    "extend",
    "insert",
    "pop",
    "remove",
    "clear",
    "sort",
    "reverse",
    "items",
    "keys",
    "values",
    "get",
    "setdefault",
    "update",
    "copy",
    "add",
    "discard",
    "put",
    "put_nowait",
    "write",
    "read",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "flush",
    "close",
    "send",
    "recv",
    "emit",
    "publish",
    "save",
    "delete",
    "commit",
    "rollback",
    "execute",
    "fetchone",
    "fetchall",
}

VALUE_TYPE_HINTS = {
    "Dict": "dict",
    "List": "list",
    "Set": "set",
    "Tuple": "tuple",
    "Constant": "constant",
    "JoinedStr": "string",
    "Name": "name_ref",
    "Call": "call_result",
    "BinOp": "binop",
    "BoolOp": "boolop",
    "IfExp": "ifexp",
    "Subscript": "subscript",
    "DictComp": "dictcomp",
    "ListComp": "listcomp",
    "SetComp": "setcomp",
    "GeneratorExp": "generatorexp",
}


CALL_RESULT_MAPPING_SOURCES = {
    "yaml.safe_load",
    "json.load",
    "json.loads",
}

CALL_RESULT_PATH_SOURCES = {
    "Path",
    "Path.resolve",
}

CALL_RESULT_TEMPLATE_SOURCES = {
    "Jinja2Templates",
}

CALL_RESULT_DB_CONNECTION_SOURCES = {
    "sqlite3.connect",
}

CALL_RESULT_DB_CURSOR_SOURCES = {
    "conn.execute",
}

CALL_RESULT_QUEUE_SOURCES = {
    "asyncio.Queue",
}

CALL_RESULT_CONTEXTVAR_SOURCES = {
    "ContextVar",
}

CALL_RESULT_MODULE_SOURCES = {
    "importlib.import_module",
}

CALL_RESULT_STRING_SOURCES = {
    "str",
    "repr",
}

CALL_RESULT_SEQUENCE_SOURCES = {
    "list",
    "sorted",
    "tuple",
    "set",
}

CALL_RESULT_COUNTERLIKE_SOURCES = {
    "Counter",
    "defaultdict",
}


def make_file_node_id(file_path: str) -> str:
    return f"file:{file_path}"


def make_symbol_node_id(file_path: str, scope: str, name: str, kind: str) -> str:
    return f"{kind}:{file_path}:{scope}:{name}"


def _path_is_package_init(file_path: str) -> bool:
    return PurePosixPath(file_path).name == "__init__.py"


def _package_parts_for_file(module_name: str, file_path: str) -> list[str]:
    if module_name == "__root__":
        return []

    parts = module_name.split(".")
    if _path_is_package_init(file_path):
        return parts
    return parts[:-1]


def _resolve_module_reference(source_module: str, source_file_path: str, module_ref: str | None) -> str | None:
    if module_ref is None:
        return None

    if not module_ref.startswith("."):
        return module_ref or None

    level = 0
    while level < len(module_ref) and module_ref[level] == ".":
        level += 1

    remainder = module_ref[level:]
    package_parts = _package_parts_for_file(source_module, source_file_path)

    up = max(level - 1, 0)
    if up > len(package_parts):
        base_parts: list[str] = []
    else:
        base_parts = package_parts[: len(package_parts) - up]

    if remainder:
        resolved_parts = base_parts + remainder.split(".")
    else:
        resolved_parts = base_parts

    return ".".join(part for part in resolved_parts if part) or "__root__"


def _module_candidates_for_import(name: str) -> list[str]:
    parts = name.split(".")
    candidates = [".".join(parts[: idx + 1]) for idx in range(len(parts))]
    return list(reversed(candidates))


def _target_module_from_import_name(import_name: str, module_to_file: dict[str, str]) -> str | None:
    for candidate in _module_candidates_for_import(import_name):
        if candidate in module_to_file:
            return candidate
    return None


def _build_scope_to_node_id(nodes: list[NodeRecord], file_path: str) -> dict[str, str]:
    result: dict[str, str] = {}

    for node in nodes:
        if node.file_path != file_path or node.node_type == "file":
            continue

        if node.node_type == "class":
            result[f"{node.scope} > class:{node.name}"] = node.node_id
        else:
            result[f"{node.scope} > function:{node.name}"] = node.node_id

    return result


def _build_file_symbol_indexes(
    nodes: list[NodeRecord],
) -> tuple[dict[str, dict[str, list[str]]], dict[str, dict[str, list[str]]]]:
    by_file_simple: dict[str, dict[str, list[str]]] = {}
    by_file_methods: dict[str, dict[str, list[str]]] = {}

    for node in nodes:
        if node.node_type == "file":
            continue

        by_file_simple.setdefault(node.file_path, {}).setdefault(node.name, []).append(node.node_id)

        if node.node_type in {"method", "async_method"}:
            by_file_methods.setdefault(node.file_path, {}).setdefault(node.name, []).append(node.node_id)

    return by_file_simple, by_file_methods


def _top_level_module_name(name: str) -> str:
    return name.split(".", 1)[0] if name else ""


def _is_probably_external_module(module_name: str, local_roots: set[str]) -> bool:
    if not module_name or module_name == "__root__":
        return False

    top = _top_level_module_name(module_name)
    if top in local_roots:
        return False
    if top in STDLIB_MODULES:
        return True
    return True


def _same_file_symbol_candidates(
    file_path: str,
    name: str,
    file_symbol_index: dict[str, dict[str, list[str]]],
) -> list[str]:
    return file_symbol_index.get(file_path, {}).get(name, [])


def _normalize_value_type(value_type: str) -> str:
    return VALUE_TYPE_HINTS.get(value_type, value_type.lower())


def _merge_hint(existing: str | None, new_hint: str) -> str:
    if existing is None:
        return new_hint
    if existing == new_hint:
        return existing
    return f"mixed:{existing}|{new_hint}"


def _extract_call_source_name(value_repr: str) -> str | None:
    if not value_repr:
        return None

    text = value_repr.strip()
    if not text:
        return None

    first_paren = text.find("(")
    if first_paren == -1:
        return None

    return text[:first_paren].strip() or None


def _build_call_result_hint(value_repr: str) -> str:
    call_source = _extract_call_source_name(value_repr)
    if call_source:
        return f"call_result:{call_source}"
    return "call_result"


_SKIP_ANNOTATION_NAMES = frozenset({
    "Optional", "Union", "List", "Dict", "Tuple", "Set", "FrozenSet",
    "Sequence", "Iterable", "Iterator", "Generator", "Callable",
    "Any", "Type", "ClassVar", "Final", "Literal", "Annotated",
    "TypeVar", "Generic", "Protocol", "Awaitable", "Coroutine",
})


def _annotation_to_class_name(annotation: str) -> str | None:
    """Extract the first probable local class name from a type annotation string.

    Handles 'ClassName', 'Optional[ClassName]', 'ClassName | None', etc.
    Skips generic container names (Optional, Union, List, ...).
    """
    token = ""
    for ch in annotation:
        if ch.isalnum() or ch == "_":
            token += ch
        else:
            if token and token[0].isupper() and token not in _SKIP_ANNOTATION_NAMES:
                return token
            token = ""
    if token and token[0].isupper() and token not in _SKIP_ANNOTATION_NAMES:
        return token
    return None


def _build_variable_type_hints(file_record: dict[str, Any]) -> dict[str, dict[str, str]]:
    hints: dict[str, dict[str, str]] = {}

    for assignment in file_record.get("assignments", []):
        scope = assignment.get("enclosing_scope", "module")
        raw_value_type = assignment.get("value_type", "unknown")
        value_repr = assignment.get("value_repr", "")
        value_type = _normalize_value_type(raw_value_type)

        if value_type == "call_result":
            value_type = _build_call_result_hint(value_repr)

        targets = assignment.get("targets", [])
        scope_hints = hints.setdefault(scope, {})

        for target in targets:
            if not target:
                continue
            if "." in target or "[" in target or "(" in target or "{" in target:
                continue

            scope_hints[target] = _merge_hint(scope_hints.get(target), value_type)

    # Add parameter type annotations from method and function signatures.
    # This allows Phase 4a to resolve calls like context.require() when the
    # enclosing function declares context: CapabilityContext.
    for cls_record in file_record.get("classes", []):
        for method in cls_record.get("methods", []):
            body_scope = method["enclosing_scope"] + " > function:" + method["name"]
            scope_hints = hints.setdefault(body_scope, {})
            for param_name, annotation in method.get("arg_annotations", {}).items():
                if param_name == "self":
                    continue
                type_name = _annotation_to_class_name(annotation)
                if type_name:
                    scope_hints[param_name] = _merge_hint(scope_hints.get(param_name), type_name)

    for fn_record in file_record.get("functions", []):
        body_scope = fn_record["enclosing_scope"] + " > function:" + fn_record["name"]
        scope_hints = hints.setdefault(body_scope, {})
        for param_name, annotation in fn_record.get("arg_annotations", {}).items():
            type_name = _annotation_to_class_name(annotation)
            if type_name:
                scope_hints[param_name] = _merge_hint(scope_hints.get(param_name), type_name)

    return hints


def _lookup_variable_hint(
    variable_hints_by_scope: dict[str, dict[str, str]],
    source_scope: str,
    variable_name: str,
) -> str | None:
    if source_scope in variable_hints_by_scope and variable_name in variable_hints_by_scope[source_scope]:
        return variable_hints_by_scope[source_scope][variable_name]

    if source_scope == "module":
        return variable_hints_by_scope.get("module", {}).get(variable_name)

    parts = source_scope.split(" > ")
    while len(parts) > 1:
        parts = parts[:-1]
        parent_scope = " > ".join(parts)
        if variable_name in variable_hints_by_scope.get(parent_scope, {}):
            return variable_hints_by_scope[parent_scope][variable_name]

    return variable_hints_by_scope.get("module", {}).get(variable_name)


def _primary_hint_value(variable_hint: str) -> str:
    if variable_hint.startswith("mixed:"):
        return variable_hint[len("mixed:") :].split("|", 1)[0]
    return variable_hint


def _call_source_from_hint(variable_hint: str) -> str | None:
    primary = _primary_hint_value(variable_hint)
    if primary.startswith("call_result:"):
        return primary.split(":", 1)[1]
    return None


def _class_name_from_scope(scope: str) -> str | None:
    """Extract the immediately enclosing class name from a scope string.

    e.g. 'module > class:Builder > function:run' -> 'Builder'
    """
    for part in reversed(scope.split(" > ")):
        if part.startswith("class:"):
            return part[6:]
    return None


def _build_class_attr_type_index(
    files: list[dict],
    class_file_index: dict[str, list[str]],
) -> dict[str, dict[str, str]]:
    """Build {class_name: {attr_name: type_class_name}} from __init__ assignments.

    Handles two patterns:
    - Direct constructor: self.attr = LocalClass(...)
    - DI parameter:       self.attr = param where param: LocalClass in __init__ signature
    """
    # Build per-class __init__ parameter annotation map first
    init_param_types: dict[str, dict[str, str]] = {}  # class_name -> {param: type}
    for file_record in files:
        if "parse_error" in file_record:
            continue
        for cls_record in file_record.get("classes", []):
            for method in cls_record.get("methods", []):
                if method.get("name") != "__init__":
                    continue
                for param_name, annotation in method.get("arg_annotations", {}).items():
                    if param_name == "self":
                        continue
                    type_name = _annotation_to_class_name(annotation)
                    if type_name and type_name in class_file_index:
                        init_param_types.setdefault(cls_record["name"], {})[param_name] = type_name

    index: dict[str, dict[str, str]] = {}
    for file_record in files:
        if "parse_error" in file_record:
            continue
        for assignment in file_record.get("assignments", []):
            scope = assignment.get("enclosing_scope", "")
            if not scope.endswith("function:__init__"):
                continue
            class_name = _class_name_from_scope(scope)
            if not class_name:
                continue
            value_type = assignment.get("value_type", "")
            value_repr = assignment.get("value_repr", "")

            resolved_type: str | None = None

            if value_type == "Call":
                # Pattern 1: self.attr = LocalClass(...)
                paren_pos = value_repr.find("(")
                if paren_pos > 0:
                    ctor_expr = value_repr[:paren_pos].strip()
                    ctor_name = ctor_expr.rsplit(".", 1)[-1] if "." in ctor_expr else ctor_expr
                    if ctor_name and ctor_name[0].isupper() and ctor_name in class_file_index:
                        resolved_type = ctor_name

            elif value_type == "Name" and value_repr:
                # Pattern 2: self.attr = param where param has an annotated local type
                resolved_type = init_param_types.get(class_name, {}).get(value_repr)

            if resolved_type is None:
                continue

            for target in assignment.get("targets", []):
                if not target.startswith("self."):
                    continue
                rest = target[5:]
                if not rest or "." in rest or "[" in rest:
                    continue
                index.setdefault(class_name, {})[rest] = resolved_type

    return index


def _class_name_from_hint(hint: str) -> str | None:
    """Extract a probable class name from a variable type hint for method resolution.

    Handles:
    - call_result:ClassName  — variable is the result of constructing ClassName(...)
    - ClassName              — variable has a known class type (uppercase first letter)
    """
    primary = _primary_hint_value(hint)
    if primary.startswith("call_result:"):
        candidate = primary[len("call_result:"):]
        if candidate and candidate[0].isupper():
            return candidate
    elif primary and primary[0].isupper() and primary not in ("True", "False", "None"):
        return primary
    return None


def _classify_call_result_source(call_source: str, tail: str, chained: bool) -> str:
    if call_source in CALL_RESULT_MAPPING_SOURCES:
        return "mapping_like_call_result_method_chain" if chained else "mapping_like_call_result_method"

    if call_source in CALL_RESULT_PATH_SOURCES:
        return "path_like_call_result_method_chain" if chained else "path_like_call_result_method"

    if call_source in CALL_RESULT_TEMPLATE_SOURCES:
        return "template_engine_method_chain" if chained else "template_engine_method"

    if call_source in CALL_RESULT_DB_CONNECTION_SOURCES:
        return "db_connection_method_chain" if chained else "db_connection_method"

    if call_source in CALL_RESULT_DB_CURSOR_SOURCES:
        return "db_cursor_method_chain" if chained else "db_cursor_method"

    if call_source in CALL_RESULT_QUEUE_SOURCES:
        return "queue_like_call_result_method_chain" if chained else "queue_like_call_result_method"

    if call_source in CALL_RESULT_CONTEXTVAR_SOURCES:
        return "contextvar_like_call_result_method_chain" if chained else "contextvar_like_call_result_method"

    if call_source in CALL_RESULT_MODULE_SOURCES:
        return "module_like_call_result_method_chain" if chained else "module_like_call_result_method"

    if call_source in CALL_RESULT_STRING_SOURCES:
        return "string_method_chain" if chained else "string_method"

    if call_source in CALL_RESULT_SEQUENCE_SOURCES:
        return "sequence_like_call_result_method_chain" if chained else "sequence_like_call_result_method"

    if call_source in CALL_RESULT_COUNTERLIKE_SOURCES:
        return "counter_like_call_result_method_chain" if chained else "counter_like_call_result_method"

    if tail in COMMON_CONTAINER_METHODS:
        return "call_result_container_method_chain" if chained else "call_result_container_method"

    return "call_result_method_chain" if chained else "call_result_method"


def _classify_typed_method(variable_hint: str, tail: str, chained: bool) -> str:
    base = _primary_hint_value(variable_hint)

    if base == "dict":
        return "dict_method_chain" if chained else "dict_method"
    if base == "list":
        return "list_method_chain" if chained else "list_method"
    if base == "set":
        return "set_method_chain" if chained else "set_method"
    if base == "tuple":
        return "tuple_method_chain" if chained else "tuple_method"
    if base == "string":
        return "string_method_chain" if chained else "string_method"
    if base == "constant":
        return "constant_method_chain" if chained else "constant_method"
    if base == "name_ref":
        return "name_ref_method_chain" if chained else "name_ref_method"

    if base.startswith("call_result:"):
        call_source = _call_source_from_hint(base)
        if call_source:
            return _classify_call_result_source(call_source, tail, chained)
        return "call_result_method_chain" if chained else "call_result_method"

    if base == "call_result":
        if tail in COMMON_CONTAINER_METHODS:
            return "call_result_container_method_chain" if chained else "call_result_container_method"
        return "call_result_method_chain" if chained else "call_result_method"

    if tail in COMMON_CONTAINER_METHODS:
        return "typed_container_method_chain" if chained else "typed_container_method"

    return "typed_attribute_call_on_variable"


def _classify_unresolved_call(
    called_name: str,
    resolution_kind: str,
    alias_info: dict[str, Any] | None,
    variable_hint: str | None,
) -> str:
    parts = called_name.split(".")
    head = parts[0]
    tail = parts[-1] if parts else called_name
    is_chained_expression = "(" in called_name or "[" in called_name or "{" in called_name

    if resolution_kind == "builtin":
        return "builtin_call"

    if alias_info and alias_info["kind"] in {"external_module", "external_symbol"}:
        return "external_alias_call"

    if resolution_kind == "ambiguous_local_symbol":
        return "ambiguous_local_symbol"

    if resolution_kind == "ambiguous_global_symbol":
        return "ambiguous_global_symbol"

    if resolution_kind == "imported_symbol":
        return "ambiguous_imported_symbol"

    if variable_hint is not None:
        return _classify_typed_method(variable_hint, tail, is_chained_expression)

    if resolution_kind == "external_or_unresolved_module_attr":
        if tail in COMMON_CONTAINER_METHODS:
            return "container_or_object_method"
        return "imported_module_attribute_call"

    if len(parts) > 1:
        if is_chained_expression:
            return "chained_expression_call"
        if tail in COMMON_CONTAINER_METHODS:
            return "container_or_object_method"
        if head and head[0].islower():
            return "attribute_call_on_variable"
        return "dotted_attribute_call"

    if head in COMMON_CONTAINER_METHODS:
        return "container_or_object_method"

    return "unresolved_internal_call"


def _resolve_call_target(
    called_name: str,
    source_file: str,
    import_alias_index: dict[str, dict[str, dict[str, Any]]],
    file_symbol_index: dict[str, dict[str, list[str]]],
    file_method_index: dict[str, dict[str, list[str]]],
    global_symbol_name_index: dict[str, list[str]],
) -> tuple[str | None, str]:
    parts = called_name.split(".")
    head = parts[0]

    if head in BUILTIN_NAMES:
        return None, "builtin"

    if len(parts) == 1:
        local_candidates = _same_file_symbol_candidates(source_file, head, file_symbol_index)
        if len(local_candidates) == 1:
            return local_candidates[0], "local_symbol"
        if len(local_candidates) > 1:
            return None, "ambiguous_local_symbol"

        imported = import_alias_index.get(source_file, {}).get(head)
        if imported:
            if imported["kind"] == "symbol":
                targets = imported["target_ids"]
                if len(targets) == 1:
                    return targets[0], "imported_symbol"
                return None, "imported_symbol"
            return None, imported["kind"]

        global_candidates = global_symbol_name_index.get(head, [])
        if len(global_candidates) == 1:
            return global_candidates[0], "global_unique_symbol"
        if len(global_candidates) > 1:
            return None, "ambiguous_global_symbol"

        return None, "unresolved"

    imported = import_alias_index.get(source_file, {}).get(head)
    if imported:
        if imported["kind"] == "module":
            target_file = imported["target_file"]
            tail = parts[-1]

            method_candidates = file_method_index.get(target_file, {}).get(tail, [])
            if len(method_candidates) == 1:
                return method_candidates[0], "imported_module_method"

            symbol_candidates = file_symbol_index.get(target_file, {}).get(tail, [])
            if len(symbol_candidates) == 1:
                return symbol_candidates[0], "imported_module_symbol"

            return None, "external_or_unresolved_module_attr"

        if imported["kind"] == "symbol":
            targets = imported["target_ids"]
            if len(targets) == 1:
                return targets[0], "imported_symbol_attr_base"
            return None, "imported_symbol"

    local_base_candidates = _same_file_symbol_candidates(source_file, head, file_symbol_index)
    if len(local_base_candidates) == 1:
        tail = parts[-1]
        method_candidates = file_method_index.get(source_file, {}).get(tail, [])
        if len(method_candidates) == 1:
            return method_candidates[0], "same_file_method"

        return local_base_candidates[0], "same_file_symbol_base"

    if len(local_base_candidates) > 1:
        return None, "ambiguous_local_symbol"

    return None, "unresolved"


def _detect_python_path_roots(files: list[dict]) -> list[str]:
    """Detect directories that act as Python path roots (sys.path entries).

    A Python path root is a directory that contains at least one immediate child
    that is a Python package (has __init__.py), but is not itself a Python package.

    When multiple candidates are found, subdirectory candidates are discarded in
    favour of the shallowest ancestor: e.g. if both 'src' and 'src/backup' qualify,
    only 'src' is kept. This prevents backup or copy subdirectories from being
    treated as independent Python path roots and creating ambiguous module names.

    Returns a sorted list of directory paths as POSIX strings.
    Empty string '' means the repo root itself.
    """
    package_dirs: set[str] = set()
    for file_record in files:
        if "parse_error" in file_record:
            continue
        p = PurePosixPath(file_record["path"])
        if p.name == "__init__.py" and len(p.parts) > 1:
            package_dirs.add(str(p.parent))

    # Collect raw candidates: non-package directories that directly contain packages
    raw_roots: set[str] = set()
    for pkg_dir in package_dirs:
        parent_p = PurePosixPath(pkg_dir).parent
        parent = "" if str(parent_p) == "." else str(parent_p)
        if parent not in package_dirs:
            raw_roots.add(parent)

    # Discard any candidate that is a subdirectory of another candidate.
    # This keeps only the shallowest (most general) Python path roots.
    filtered: set[str] = set()
    for root in raw_roots:
        is_subdir = any(
            root.startswith(other + "/")
            for other in raw_roots
            if other != root and other != ""
        )
        if not is_subdir:
            filtered.add(root)

    return sorted(filtered)


def _build_alt_module_index(
    files: list[dict],
    primary_module_to_file: dict[str, str],
    python_path_roots: list[str],
) -> dict[str, str]:
    """Build alternative module name mappings from detected Python path roots.

    For each detected root that is not the repo root, computes module names for
    files relative to that root. Only adds entries that are:
      - not already present in primary_module_to_file
      - unambiguous: exactly one file maps to that alternative name

    This allows imports anchored at a subdirectory (e.g. 'from api.routes import X'
    in a repo where all packages live under 'src/') to resolve correctly.
    """
    # Collect candidates across all non-root roots, grouped by alt name
    all_candidates: dict[str, list[str]] = {}

    for root in python_path_roots:
        if root == "":
            continue

        root_prefix = root + "/"

        for file_record in files:
            if "parse_error" in file_record:
                continue
            path = file_record["path"]
            if not path.startswith(root_prefix):
                continue

            rel = path[len(root_prefix):]
            parts = list(PurePosixPath(rel).parts)
            if not parts:
                continue

            if len(parts) == 1 and parts[0] == "__init__.py":
                continue  # root __init__.py from this anchor — skip
            elif parts[-1] == "__init__.py":
                parts = parts[:-1]
                alt_name = ".".join(parts)
            elif parts[-1].endswith(".py"):
                parts[-1] = parts[-1][:-3]
                alt_name = ".".join(parts)
            else:
                continue

            if alt_name:
                if path not in all_candidates.get(alt_name, []):
                    all_candidates.setdefault(alt_name, []).append(path)

    # Only add unambiguous mappings not already in the primary index
    result: dict[str, str] = {}
    for alt_name, paths in all_candidates.items():
        if len(paths) == 1 and alt_name not in primary_module_to_file:
            result[alt_name] = paths[0]

    return result


def build_relation_map(inventory: dict) -> dict:
    files = inventory["files"]

    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []
    unresolved_calls: list[dict[str, Any]] = []
    unresolved_imports: list[dict[str, Any]] = []
    external_imports: list[dict[str, Any]] = []
    external_calls: list[dict[str, Any]] = []

    module_to_file: dict[str, str] = {}
    file_nodes: dict[str, str] = {}
    symbol_nodes: dict[tuple[str, str, str, str], str] = {}
    file_variable_hints: dict[str, dict[str, dict[str, str]]] = {}

    for file_record in files:
        if "parse_error" in file_record:
            continue
        module_to_file[file_record["module_name"]] = file_record["path"]
        file_variable_hints[file_record["path"]] = _build_variable_type_hints(file_record)

    # Detect Python path roots and extend the module index with alternative names.
    # This handles repos where packages are anchored at a subdirectory rather than
    # the repo root (e.g. src/ layouts, or projects run from inside a subdirectory).
    python_path_roots = _detect_python_path_roots(files)
    alt_module_to_file = _build_alt_module_index(files, module_to_file, python_path_roots)
    module_to_file.update(alt_module_to_file)

    local_roots = {
        _top_level_module_name(module_name)
        for module_name in module_to_file
        if module_name and module_name != "__root__"
    }

    for file_record in files:
        if "parse_error" in file_record:
            continue

        file_path = file_record["path"]
        file_node_id = make_file_node_id(file_path)
        file_nodes[file_path] = file_node_id

        nodes.append(
            NodeRecord(
                node_id=file_node_id,
                node_type="file",
                file_path=file_path,
                name=file_path,
                scope="module",
                lineno=None,
                end_lineno=None,
            )
        )

        for fn in file_record.get("functions", []):
            node_id = make_symbol_node_id(
                file_path=file_path,
                scope=fn["enclosing_scope"],
                name=fn["name"],
                kind=fn["function_type"],
            )
            symbol_nodes[(file_path, fn["enclosing_scope"], fn["name"], fn["function_type"])] = node_id

            nodes.append(
                NodeRecord(
                    node_id=node_id,
                    node_type=fn["function_type"],
                    file_path=file_path,
                    name=fn["name"],
                    scope=fn["enclosing_scope"],
                    lineno=fn["lineno"],
                    end_lineno=fn["end_lineno"],
                )
            )
            edges.append(
                EdgeRecord(
                    edge_type="contains",
                    source_id=file_node_id,
                    target_id=node_id,
                    evidence="function definition",
                    lineno=fn["lineno"],
                    end_lineno=fn["end_lineno"],
                )
            )

        for cls in file_record.get("classes", []):
            class_node_id = make_symbol_node_id(
                file_path=file_path,
                scope=cls["enclosing_scope"],
                name=cls["name"],
                kind="class",
            )
            symbol_nodes[(file_path, cls["enclosing_scope"], cls["name"], "class")] = class_node_id

            nodes.append(
                NodeRecord(
                    node_id=class_node_id,
                    node_type="class",
                    file_path=file_path,
                    name=cls["name"],
                    scope=cls["enclosing_scope"],
                    lineno=cls["lineno"],
                    end_lineno=cls["end_lineno"],
                )
            )
            edges.append(
                EdgeRecord(
                    edge_type="contains",
                    source_id=file_node_id,
                    target_id=class_node_id,
                    evidence="class definition",
                    lineno=cls["lineno"],
                    end_lineno=cls["end_lineno"],
                )
            )

            for method in cls.get("methods", []):
                method_node_id = make_symbol_node_id(
                    file_path=file_path,
                    scope=method["enclosing_scope"],
                    name=method["name"],
                    kind=method["function_type"],
                )
                symbol_nodes[(file_path, method["enclosing_scope"], method["name"], method["function_type"])] = method_node_id

                nodes.append(
                    NodeRecord(
                        node_id=method_node_id,
                        node_type=method["function_type"],
                        file_path=file_path,
                        name=method["name"],
                        scope=method["enclosing_scope"],
                        lineno=method["lineno"],
                        end_lineno=method["end_lineno"],
                    )
                )
                edges.append(
                    EdgeRecord(
                        edge_type="contains",
                        source_id=class_node_id,
                        target_id=method_node_id,
                        evidence="method definition",
                        lineno=method["lineno"],
                        end_lineno=method["end_lineno"],
                    )
                )

    file_symbol_index, file_method_index = _build_file_symbol_indexes(nodes)

    global_symbol_name_index: dict[str, list[str]] = {}
    class_file_index: dict[str, list[str]] = {}  # class_name -> [file_path]
    for node in nodes:
        if node.node_type != "file":
            global_symbol_name_index.setdefault(node.name, []).append(node.node_id)
        if node.node_type == "class":
            if node.file_path not in class_file_index.get(node.name, []):
                class_file_index.setdefault(node.name, []).append(node.file_path)

    class_attr_type_index = _build_class_attr_type_index(files, class_file_index)

    import_alias_index: dict[str, dict[str, dict[str, Any]]] = {}

    for file_record in files:
        if "parse_error" in file_record:
            continue

        file_path = file_record["path"]
        file_node_id = file_nodes[file_path]
        source_module = file_record["module_name"]

        alias_map_for_file: dict[str, dict[str, Any]] = {}

        for item in file_record.get("imports", []):
            if item["import_type"] == "import":
                for name in item["names"]:
                    resolved_module = _target_module_from_import_name(name, module_to_file)
                    alias_name = item["alias_map"].get(name, name.split(".")[0])

                    if resolved_module and resolved_module in module_to_file:
                        target_file = module_to_file[resolved_module]
                        edges.append(
                            EdgeRecord(
                                edge_type="imports",
                                source_id=file_node_id,
                                target_id=file_nodes[target_file],
                                evidence=f"import {name}",
                                lineno=item["lineno"],
                                end_lineno=item["end_lineno"],
                            )
                        )
                        alias_map_for_file[alias_name] = {
                            "kind": "module",
                            "target_module": resolved_module,
                            "target_file": target_file,
                        }
                    else:
                        if _is_probably_external_module(name, local_roots):
                            external_imports.append(
                                {
                                    "source_file": file_path,
                                    "import_text": f"import {name}",
                                    "lineno": item["lineno"],
                                    "end_lineno": item["end_lineno"],
                                }
                            )
                            alias_map_for_file[alias_name] = {
                                "kind": "external_module",
                                "target_module": name,
                                "target_file": None,
                            }
                        else:
                            unresolved_imports.append(
                                {
                                    "source_file": file_path,
                                    "import_text": f"import {name}",
                                    "lineno": item["lineno"],
                                    "end_lineno": item["end_lineno"],
                                }
                            )

            elif item["import_type"] == "from_import":
                raw_module = item["module"]
                resolved_module = _resolve_module_reference(source_module, file_path, raw_module)

                if resolved_module and resolved_module in module_to_file:
                    target_file = module_to_file[resolved_module]
                    edges.append(
                        EdgeRecord(
                            edge_type="imports",
                            source_id=file_node_id,
                            target_id=file_nodes[target_file],
                            evidence=f"from {raw_module} import {', '.join(item['names'])}",
                            lineno=item["lineno"],
                            end_lineno=item["end_lineno"],
                        )
                    )

                    for imported_name in item["names"]:
                        alias_name = item["alias_map"].get(imported_name, imported_name)
                        module_symbol_candidates = file_symbol_index.get(target_file, {}).get(imported_name, [])

                        if module_symbol_candidates:
                            alias_map_for_file[alias_name] = {
                                "kind": "symbol",
                                "target_ids": module_symbol_candidates,
                                "target_file": target_file,
                                "target_module": resolved_module,
                            }
                        else:
                            submodule_name = f"{resolved_module}.{imported_name}"
                            if submodule_name in module_to_file:
                                alias_map_for_file[alias_name] = {
                                    "kind": "module",
                                    "target_module": submodule_name,
                                    "target_file": module_to_file[submodule_name],
                                }
                            else:
                                unresolved_imports.append(
                                    {
                                        "source_file": file_path,
                                        "import_text": f"from {raw_module} import {imported_name}",
                                        "lineno": item["lineno"],
                                        "end_lineno": item["end_lineno"],
                                    }
                                )
                else:
                    if resolved_module and _is_probably_external_module(resolved_module, local_roots):
                        external_imports.append(
                            {
                                "source_file": file_path,
                                "import_text": f"from {raw_module} import {', '.join(item['names'])}",
                                "lineno": item["lineno"],
                                "end_lineno": item["end_lineno"],
                            }
                        )
                        for imported_name in item["names"]:
                            alias_name = item["alias_map"].get(imported_name, imported_name)
                            alias_map_for_file[alias_name] = {
                                "kind": "external_symbol",
                                "target_module": resolved_module,
                                "target_file": None,
                            }
                    else:
                        unresolved_imports.append(
                            {
                                "source_file": file_path,
                                "import_text": f"from {raw_module} import {', '.join(item['names'])}",
                                "lineno": item["lineno"],
                                "end_lineno": item["end_lineno"],
                            }
                        )

        import_alias_index[file_path] = alias_map_for_file

    for file_record in files:
        if "parse_error" in file_record:
            continue

        file_path = file_record["path"]
        file_node_id = file_nodes[file_path]
        scope_to_node_id = _build_scope_to_node_id(nodes, file_path)
        variable_hints_by_scope = file_variable_hints.get(file_path, {})

        for call in file_record.get("calls", []):
            source_scope = call["enclosing_scope"]
            source_id = scope_to_node_id.get(source_scope, file_node_id)

            called_name = call["called_name"]
            target_id, resolution_kind = _resolve_call_target(
                called_name=called_name,
                source_file=file_path,
                import_alias_index=import_alias_index,
                file_symbol_index=file_symbol_index,
                file_method_index=file_method_index,
                global_symbol_name_index=global_symbol_name_index,
            )

            if target_id:
                edges.append(
                    EdgeRecord(
                        edge_type="calls",
                        source_id=source_id,
                        target_id=target_id,
                        evidence=called_name,
                        lineno=call["lineno"],
                        end_lineno=call["end_lineno"],
                    )
                )
            else:
                head = called_name.split(".")[0]
                alias_info = import_alias_index.get(file_path, {}).get(head)
                variable_hint = _lookup_variable_hint(variable_hints_by_scope, source_scope, head)

                # Variable-hint class method resolution fallback (Phase 4a):
                # When a dotted call like executor.invoke() is unresolved, check
                # whether the variable hint tells us the instance's class type,
                # then look up the method in that class's file.
                if "." in called_name and variable_hint is not None and resolution_kind not in ("builtin",):
                    class_name = _class_name_from_hint(variable_hint)
                    if class_name:
                        tail_method = called_name.rsplit(".", 1)[-1]
                        candidate_files = class_file_index.get(class_name, [])
                        resolved_methods: list[str] = []
                        for cfile in candidate_files:
                            resolved_methods.extend(file_method_index.get(cfile, {}).get(tail_method, []))
                        # Only resolve when unambiguous
                        if len(resolved_methods) == 1:
                            edges.append(
                                EdgeRecord(
                                    edge_type="calls",
                                    source_id=source_id,
                                    target_id=resolved_methods[0],
                                    evidence=called_name,
                                    lineno=call["lineno"],
                                    end_lineno=call["end_lineno"],
                                )
                            )
                            continue

                # __init__ attribute type resolution fallback (Phase 16):
                # When a chained call starts with self. (self.attr.method), look up
                # attr in the enclosing class's attribute type map derived from __init__
                # assignments of the form self.attr = LocalClass(...).
                if (
                    called_name.startswith("self.")
                    and called_name.count(".") == 2
                    and resolution_kind not in ("builtin",)
                ):
                    p16 = called_name.split(".")
                    attr_name_16 = p16[1]
                    method_name_16 = p16[2]
                    enclosing_class_16 = _class_name_from_scope(source_scope)
                    if enclosing_class_16:
                        type_class_16 = class_attr_type_index.get(enclosing_class_16, {}).get(attr_name_16)
                        if type_class_16:
                            candidate_files_16 = class_file_index.get(type_class_16, [])
                            resolved_methods_16: list[str] = []
                            for cfile in candidate_files_16:
                                resolved_methods_16.extend(
                                    file_method_index.get(cfile, {}).get(method_name_16, [])
                                )
                            if len(resolved_methods_16) == 1:
                                edges.append(
                                    EdgeRecord(
                                        edge_type="calls",
                                        source_id=source_id,
                                        target_id=resolved_methods_16[0],
                                        evidence=called_name,
                                        lineno=call["lineno"],
                                        end_lineno=call["end_lineno"],
                                    )
                                )
                                continue

                if resolution_kind == "builtin":
                    external_calls.append(
                        {
                            "source_file": file_path,
                            "source_scope": source_scope,
                            "called_name": called_name,
                            "resolution_kind": "builtin_call",
                            "category": "builtin_call",
                            "variable_hint": variable_hint,
                            "lineno": call["lineno"],
                            "end_lineno": call["end_lineno"],
                        }
                    )
                elif alias_info and alias_info["kind"] in {"external_module", "external_symbol"}:
                    external_calls.append(
                        {
                            "source_file": file_path,
                            "source_scope": source_scope,
                            "called_name": called_name,
                            "resolution_kind": alias_info["kind"],
                            "category": "external_alias_call",
                            "variable_hint": variable_hint,
                            "lineno": call["lineno"],
                            "end_lineno": call["end_lineno"],
                        }
                    )
                else:
                    category = _classify_unresolved_call(
                        called_name=called_name,
                        resolution_kind=resolution_kind,
                        alias_info=alias_info,
                        variable_hint=variable_hint,
                    )
                    unresolved_calls.append(
                        {
                            "source_file": file_path,
                            "source_scope": source_scope,
                            "called_name": called_name,
                            "resolution_kind": resolution_kind,
                            "category": category,
                            "variable_hint": variable_hint,
                            "lineno": call["lineno"],
                            "end_lineno": call["end_lineno"],
                        }
                    )

    return {
        "repo_root": inventory["repo_root"],
        "scanned_at": inventory["scanned_at"],
        "file_count": inventory["file_count"],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "python_path_roots": python_path_roots,
        "nodes": [asdict(node) for node in nodes],
        "edges": [asdict(edge) for edge in edges],
        "unresolved_imports": unresolved_imports,
        "unresolved_calls": unresolved_calls,
        "external_imports": external_imports,
        "external_calls": external_calls,
    }