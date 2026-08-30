from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)

PACK_ID = "reveng.pack.file_tools"


# ---- core logic ----

def resolve_path(path):
    return Path(path).resolve()


def list_python_files_recursive(root):
    return sorted(Path(root).rglob("*.py"))


def is_scannable_python_file(path):
    parts = set(path.parts)
    return not parts.intersection({
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "node_modules",
        "dist",
        "build",
    })


def read_text_file_utf8_with_replace_fallback(py_file):
    try:
        return py_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return py_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def parse_python_ast(source, filename):
    try:
        return ast.parse(source, filename=str(filename))
    except SyntaxError:
        return None


def extract_function_sources_from_python_source(source, tree):
    class FunctionExtractor(ast.NodeVisitor):
        def __init__(self, source):
            self.source = source
            self.results = []

        def _record_function(self, node):
            try:
                source_segment = ast.get_source_segment(self.source, node)
            except Exception:
                source_segment = None

            if source_segment is None:
                lineno = getattr(node, "lineno", None)
                end_lineno = getattr(node, "end_lineno", lineno)
                if lineno is None:
                    return
                lines = self.source.splitlines()
                start = max(lineno - 1, 0)
                end = max(end_lineno, lineno)
                source_segment = "\n".join(lines[start:end])

            self.results.append(source_segment)

        def visit_FunctionDef(self, node):
            self._record_function(node)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            self._record_function(node)
            self.generic_visit(node)

    extractor = FunctionExtractor(source)
    extractor.visit(tree)
    return extractor.results


def extract_functions_from_file(py_file):
    source = read_text_file_utf8_with_replace_fallback(py_file)
    if source is None:
        return []

    tree = parse_python_ast(source, py_file)
    if tree is None:
        return []

    return extract_function_sources_from_python_source(source, tree)


def scan_repo_for_function_sources(repo_root):
    root = resolve_path(repo_root)
    all_functions = []

    for py_file in list_python_files_recursive(root):
        if not is_scannable_python_file(py_file):
            continue
        all_functions.extend(extract_functions_from_file(py_file))

    return all_functions


def write_json_file(path, data):
    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def extract_repo_functions_to_json(repo_root, output_path):
    functions = scan_repo_for_function_sources(repo_root)
    write_json_file(output_path, functions)
    return functions


# ---- capability wrappers ----

def _resolve_path_capability(context: CapabilityContext) -> dict[str, Any]:
    path = context.require("path")
    return {"resolved_path": resolve_path(path)}


def _list_python_files_recursive_capability(context: CapabilityContext) -> dict[str, Any]:
    root = context.require("root")
    return {"python_files": list_python_files_recursive(root)}


def _is_scannable_python_file_capability(context: CapabilityContext) -> dict[str, Any]:
    path = context.require("path")
    return {"scannable": is_scannable_python_file(path)}


def _read_text_file_utf8_with_replace_fallback_capability(context: CapabilityContext) -> dict[str, Any]:
    py_file = context.require("py_file")
    return {"content": read_text_file_utf8_with_replace_fallback(py_file)}


def _parse_python_ast_capability(context: CapabilityContext) -> dict[str, Any]:
    source = context.require("source")
    filename = context.require("filename")
    return {"ast_tree": parse_python_ast(source, filename)}


def _extract_function_sources_from_python_source_capability(context: CapabilityContext) -> dict[str, Any]:
    source = context.require("source")
    tree = context.require("tree")
    return {"function_sources": extract_function_sources_from_python_source(source, tree)}


def _extract_functions_from_file_capability(context: CapabilityContext) -> dict[str, Any]:
    py_file = context.require("py_file")
    return {"function_sources": extract_functions_from_file(py_file)}


def _scan_repo_for_function_sources_capability(context: CapabilityContext) -> dict[str, Any]:
    repo_root = context.require("repo_root")
    return {"function_sources": scan_repo_for_function_sources(repo_root)}


def _write_json_file_capability(context: CapabilityContext) -> dict[str, Any]:
    path = context.require("path")
    data = context.require("data")
    write_json_file(path, data)
    return {"path": str(path)}


def _extract_repo_functions_to_json_capability(context: CapabilityContext) -> dict[str, Any]:
    repo_root = context.require("repo_root")
    output_path = context.require("output_path")
    functions = extract_repo_functions_to_json(repo_root, output_path)
    return {"functions": functions, "count": len(functions)}


# ---- registration ----

def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="resolve_path",
        pack_id=PACK_ID,
        version="1",
        display_name="Resolve Path",
        description="Resolve a path to its absolute form.",
        capability_type="function",
        contract=CapabilityContract(inputs=("path",), output=("resolved_path",)),
        implementation_logic=_resolve_path_capability,
        tags=("file_tools", "path"),
    ))
    registry.register(CapabilityDefinition(
        capability_id="list_python_files_recursive",
        pack_id=PACK_ID,
        version="1",
        display_name="List Python Files Recursive",
        description="Recursively list all .py files under a root directory.",
        capability_type="function",
        contract=CapabilityContract(inputs=("root",), output=("python_files",)),
        implementation_logic=_list_python_files_recursive_capability,
        tags=("file_tools", "scan"),
    ))
    registry.register(CapabilityDefinition(
        capability_id="is_scannable_python_file",
        pack_id=PACK_ID,
        version="1",
        display_name="Is Scannable Python File",
        description="Check whether a Python file path is outside ignored directories.",
        capability_type="function",
        contract=CapabilityContract(inputs=("path",), output=("scannable",)),
        implementation_logic=_is_scannable_python_file_capability,
        tags=("file_tools", "scan"),
    ))
    registry.register(CapabilityDefinition(
        capability_id="read_text_file_utf8_with_replace_fallback",
        pack_id=PACK_ID,
        version="1",
        display_name="Read Text File UTF-8 with Replace Fallback",
        description="Read a file as UTF-8 text, falling back to error replacement on decode failure.",
        capability_type="function",
        contract=CapabilityContract(inputs=("py_file",), output=("content",)),
        implementation_logic=_read_text_file_utf8_with_replace_fallback_capability,
        tags=("file_tools", "io"),
    ))
    registry.register(CapabilityDefinition(
        capability_id="parse_python_ast",
        pack_id=PACK_ID,
        version="1",
        display_name="Parse Python AST",
        description="Parse Python source into an AST tree, returning None on syntax error.",
        capability_type="function",
        contract=CapabilityContract(inputs=("source", "filename"), output=("ast_tree",)),
        implementation_logic=_parse_python_ast_capability,
        tags=("file_tools", "ast"),
    ))
    registry.register(CapabilityDefinition(
        capability_id="extract_function_sources_from_python_source",
        pack_id=PACK_ID,
        version="1",
        display_name="Extract Function Sources from Python Source",
        description="Extract all function and async-function source segments from a parsed AST.",
        capability_type="function",
        contract=CapabilityContract(inputs=("source", "tree"), output=("function_sources",)),
        implementation_logic=_extract_function_sources_from_python_source_capability,
        tags=("file_tools", "ast"),
    ))
    registry.register(CapabilityDefinition(
        capability_id="extract_functions_from_file",
        pack_id=PACK_ID,
        version="1",
        display_name="Extract Functions from File",
        description="Extract all function source segments from a Python file.",
        capability_type="function",
        contract=CapabilityContract(inputs=("py_file",), output=("function_sources",)),
        implementation_logic=_extract_functions_from_file_capability,
        tags=("file_tools", "ast"),
    ))
    registry.register(CapabilityDefinition(
        capability_id="scan_repo_for_function_sources",
        pack_id=PACK_ID,
        version="1",
        display_name="Scan Repo for Function Sources",
        description="Walk a repo and collect all function source segments from scannable Python files.",
        capability_type="function",
        contract=CapabilityContract(inputs=("repo_root",), output=("function_sources",)),
        implementation_logic=_scan_repo_for_function_sources_capability,
        tags=("file_tools", "scan"),
    ))
    registry.register(CapabilityDefinition(
        capability_id="write_json_file",
        pack_id=PACK_ID,
        version="1",
        display_name="Write JSON File",
        description="Serialize data to a JSON file at the given path.",
        capability_type="function",
        contract=CapabilityContract(inputs=("path", "data"), output=("path",)),
        implementation_logic=_write_json_file_capability,
        tags=("file_tools", "io"),
    ))
    registry.register(CapabilityDefinition(
        capability_id="extract_repo_functions_to_json",
        pack_id=PACK_ID,
        version="1",
        display_name="Extract Repo Functions to JSON",
        description="Scan a repo for all function sources and write them to a JSON file.",
        capability_type="function",
        contract=CapabilityContract(inputs=("repo_root", "output_path"), output=("functions", "count")),
        implementation_logic=_extract_repo_functions_to_json_capability,
        tags=("file_tools", "scan", "io"),
    ))
