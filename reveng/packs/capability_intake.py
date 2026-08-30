"""
Capability intake pack — tools for the Blacksmith agent workflow.

Provides the capability boundary through which Blacksmith's workflow code
accesses draft operations, comparison logic, and the authored implementation surface.
All capabilities here must be granted to the Blacksmith agent through the standard
capability assignment path before its workflow can run.

Blacksmith workflow code calls these via capability_registry.* — never by importing
platform services directly.
"""
from __future__ import annotations

import ast
import difflib
import importlib
import inspect
import json
import uuid
from pathlib import Path
from textwrap import dedent
from typing import Any

from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)

PACK_ID = "reveng.pack.capability_intake"

# Per-capability authored directory (new path for all new authored capabilities)
_AUTHORED_DIR = Path(__file__).parent / "authored"
_AUTHORED_DIR_MODULE = "reveng.packs.authored"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_catalog_service():
    from reveng.platform.services.capability_catalog_service import CapabilityCatalogService
    return CapabilityCatalogService()


def _get_draft_service():
    from reveng.platform.services.draft_service import CapabilityDraftService
    return CapabilityDraftService()


def _get_comparison_evidence_service():
    from reveng.platform.services.comparison_evidence_service import ComparisonEvidenceService
    return ComparisonEvidenceService()


def _normalize_source(source: str) -> str:
    """Strip comments and collapse whitespace for normalized comparison."""
    try:
        tree = ast.parse(source)
        # Unparse produces normalized source without comments
        return ast.unparse(tree)
    except SyntaxError:
        # Fallback: collapse whitespace only
        return " ".join(source.split())


def _ast_dump(source: str) -> str | None:
    try:
        return ast.dump(ast.parse(source))
    except SyntaxError:
        return None


def _existing_callable_names_in_authored_dir() -> set[str]:
    """Return the set of capability IDs that already have a file in reveng/packs/authored/."""
    if not _AUTHORED_DIR.exists():
        return set()
    return {
        p.stem
        for p in _AUTHORED_DIR.glob("*.py")
        if p.stem != "__init__"
    }


def _write_function_to_authored_dir(source: str, callable_name: str) -> str:
    """
    Write an authored capability implementation to reveng/packs/authored/<callable_name>.py.

    The first function in source is renamed to 'implementation'. Returns the
    binding ref string for the new per-capability module.

    Transitional path — still called to produce a binding_ref for backward
    compatibility with capabilities that have execution_source='binding_ref'.
    New authored capabilities use execution_source='code_block' and do not
    require this file for execution (though it is still written as a reference
    copy).  Remove this function in a future phase once all authored capabilities
    have been migrated to code_block execution.
    """
    _AUTHORED_DIR.mkdir(exist_ok=True)
    init_file = _AUTHORED_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text(
            "# Authored capability implementations directory.\n"
            "# Each .py file here corresponds to one authored capability package.\n"
            "# Binding refs use the pattern: reveng.packs.authored.<capability_id>:implementation\n",
            encoding="utf-8",
        )
    renamed = _rename_first_function(source, "implementation")
    module_file = _AUTHORED_DIR / f"{callable_name}.py"
    module_file.write_text(
        f"# Authored capability: {callable_name}\n\n{renamed}\n",
        encoding="utf-8",
    )
    importlib.invalidate_caches()
    return f"{_AUTHORED_DIR_MODULE}.{callable_name}:implementation"


def _rename_first_function(source: str, new_name: str) -> str:
    """
    Return source with the first FunctionDef/AsyncFunctionDef renamed to new_name.
    Uses ast.unparse for clean output; falls back to text substitution on parse error.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.name = new_name
            break

    try:
        return ast.unparse(tree)
    except Exception:
        return source


# ---------------------------------------------------------------------------
# Capability implementations
# ---------------------------------------------------------------------------

def _parse_function_blocks(context: CapabilityContext) -> dict[str, Any]:
    """Read a Cannibal output JSON file and return the list of function source strings.

    Accepts two shapes:
      - A plain JSON list[str] (Cannibal's native output format)
      - A JSON object with a top-level "functions": list[str] key
    Raises ValueError for any other shape or if list items are not all strings.
    """
    functions_json_path = context.require("functions_json_path")
    path = Path(functions_json_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        blocks = data
    elif isinstance(data, dict) and "functions" in data:
        blocks = data["functions"]
        if not isinstance(blocks, list):
            raise ValueError(
                f"Unsupported Cannibal output shape: 'functions' key is "
                f"{type(blocks).__name__}, expected list."
            )
    else:
        raise ValueError(
            f"Unsupported Cannibal output shape: expected a JSON list or a JSON object "
            f"with a 'functions' key, got {type(data).__name__}."
        )

    non_strings = [i for i, item in enumerate(blocks) if not isinstance(item, str)]
    if non_strings:
        raise ValueError(
            f"Cannibal output list contains non-string items at indices: {non_strings}."
        )

    return {"blocks": blocks}


def _parse_function_name(context: CapabilityContext) -> dict[str, Any]:
    """Parse the name of the first function definition in source text."""
    source = context.require("source")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"name": None, "error": str(exc)}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return {"name": node.name}

    return {"name": None, "error": "no function definition found"}


def _compare_function_to_inventory(context: CapabilityContext) -> dict[str, Any]:
    """
    Compare incoming function source against the live capability inventory.

    For each installed record:
    - Uses record.code_block directly if non-empty
    - Else resolves implementation_ref → inspect.getsource()
    - Runs 5 comparison checks per target
    - is_literal_duplicate = True when exact_text_match OR ast_structural_match
    """
    source = context.require("source")
    name = context.require("name")

    catalog = _get_catalog_service()
    records = catalog.list_installed_records()

    source_stripped = source.strip()
    source_normalized = _normalize_source(source)
    source_ast_dump = _ast_dump(source)

    comparisons: list[dict[str, Any]] = []
    is_literal_duplicate = False
    duplicate_target: str | None = None

    for record in records:
        target_source: str | None = None

        if record.code_block:
            target_source = record.code_block
        elif record.implementation_ref:
            try:
                callable_obj = catalog.resolve_binding_ref(record.implementation_ref)
                target_source = inspect.getsource(callable_obj)
            except (OSError, TypeError, ValueError):
                target_source = None

        if target_source is None:
            continue

        target_stripped = target_source.strip()
        target_normalized = _normalize_source(target_source)
        target_ast_dump = _ast_dump(target_source)

        exact = source_stripped == target_stripped
        normalized = source_normalized == target_normalized
        ast_match = (
            source_ast_dump is not None
            and target_ast_dump is not None
            and source_ast_dump == target_ast_dump
        )
        name_match = name in (record.capability_id, record.display_name)
        similarity = difflib.SequenceMatcher(
            None, source_stripped, target_stripped
        ).ratio()

        literal_dup = exact or ast_match
        if literal_dup and not is_literal_duplicate:
            is_literal_duplicate = True
            duplicate_target = record.capability_id

        comparisons.append({
            "target_capability_id": record.capability_id,
            "exact_text_match": exact,
            "normalized_text_match": normalized,
            "ast_structural_match": ast_match,
            "function_name_match": name_match,
            "similarity_score": round(similarity, 4),
            "feature_breakdown": {
                "exact_text_match": exact,
                "normalized_text_match": normalized,
                "ast_structural_match": ast_match,
                "function_name_match": name_match,
                "similarity_score": round(similarity, 4),
            },
        })

    return {
        "function_name": name,
        "comparisons": comparisons,
        "is_literal_duplicate": is_literal_duplicate,
        "duplicate_target": duplicate_target,
    }


def _write_function_to_authored_module(context: CapabilityContext) -> dict[str, Any]:
    """
    Write an authored capability implementation to reveng/packs/authored/<id>.py.

    Checks both live capability_records and the authored/ directory for name
    conflicts. If a conflict exists, appends a short UUID suffix to the internal
    callable name. The display_name always remains the original clean name.

    New implementations are written as per-capability files under reveng/packs/authored/.
    The legacy authored_capabilities.py monolith is no longer written to.

    Returns: {implementation_ref, capability_id, display_name}
    """
    source = context.require("source")
    name = context.require("name")

    # Check live DB for capability_id collision
    catalog = _get_catalog_service()
    installed_ids = set(catalog.list_installed_capability_ids())

    # Check authored/ directory for file name collision
    existing_callables = _existing_callable_names_in_authored_dir()

    if name in installed_ids or name in existing_callables:
        callable_name = f"{name}_{uuid.uuid4().hex[:8]}"
    else:
        callable_name = name

    implementation_ref = _write_function_to_authored_dir(source, callable_name)

    return {
        "implementation_ref": implementation_ref,
        "capability_id": callable_name,
        "display_name": name,
    }


def _record_comparison_evidence(context: CapabilityContext) -> dict[str, Any]:
    """Record comparison evidence rows for all (candidate, target) pairs in an evidence dict."""
    run_id = context.require("run_id")
    evidence = context.require("evidence")

    svc = _get_comparison_evidence_service()
    candidate_name = evidence.get("function_name", "")
    comparisons = evidence.get("comparisons", [])
    is_literal_dup = bool(evidence.get("is_literal_duplicate", False))
    duplicate_target = evidence.get("duplicate_target")

    evidence_ids: list[str] = []
    for comp in comparisons:
        target_id = comp.get("target_capability_id", "")
        # Mark the specific duplicate target row
        row_is_dup = is_literal_dup and target_id == duplicate_target
        eid = svc.record(
            run_id=run_id,
            candidate_function_name=candidate_name,
            target_capability_id=target_id,
            exact_text_match=bool(comp.get("exact_text_match", False)),
            normalized_text_match=bool(comp.get("normalized_text_match", False)),
            ast_structural_match=bool(comp.get("ast_structural_match", False)),
            function_name_match=bool(comp.get("function_name_match", False)),
            similarity_score=float(comp.get("similarity_score", 0.0)),
            feature_breakdown=comp.get("feature_breakdown", {}),
            is_literal_duplicate=row_is_dup,
        )
        evidence_ids.append(eid)

    # If no comparisons (empty inventory), record a single no-target row
    if not comparisons:
        eid = svc.record(
            run_id=run_id,
            candidate_function_name=candidate_name,
            target_capability_id="",
            exact_text_match=False,
            normalized_text_match=False,
            ast_structural_match=False,
            function_name_match=False,
            similarity_score=0.0,
            feature_breakdown={},
            is_literal_duplicate=False,
        )
        evidence_ids.append(eid)

    return {"evidence_ids": evidence_ids, "count": len(evidence_ids)}


def _create_capability_draft(context: CapabilityContext) -> dict[str, Any]:
    """Create a new capability draft and return its draft_id."""
    name = context.require("name")
    svc = _get_draft_service()
    draft = svc.create_draft(name=name)
    return {"draft_id": draft.id}


def _fill_draft_with_function(context: CapabilityContext) -> dict[str, Any]:
    """
    Add a draft item with minimal honest fields to an existing draft.

    draft_data supplied:
      capability_id, display_name, capability_type, pack_id, implementation_ref, code_block

    capability_id is written explicitly into draft_data AND passed as planned_capability_id.
    """
    draft_id = context.require("draft_id")
    name = context.require("name")           # display_name (clean human name)
    capability_id = context.require("capability_id")   # internal ID, may have suffix
    code_block = context.require("code_block")
    implementation_ref = context.require("implementation_ref")

    draft_data = {
        "capability_id": capability_id,
        "display_name": name,
        "capability_type": "function",
        "pack_id": "reveng.pack.authored",
        "implementation_ref": implementation_ref,
        "code_block": code_block,
        "execution_source": "code_block",
    }

    svc = _get_draft_service()
    item = svc.add_draft_item(
        draft_id,
        planned_capability_id=capability_id,
        draft_data=draft_data,
    )
    return {"item_id": item.id}


def _validate_and_publish_draft(context: CapabilityContext) -> dict[str, Any]:
    """
    Validate then publish a draft atomically.

    If validation fails for any item, the draft is deleted and a structured failure
    dict is returned. Blacksmith must never leave orphaned drafts.

    Returns:
        {"ok": True} on full success.
        {"ok": False, "stage": "validate"|"publish"|"exception", "error": str, "details": ...}
        on failure.
    """
    draft_id = context.require("draft_id")
    svc = _get_draft_service()

    try:
        val_result = svc.validate_draft(draft_id)
        failed = [r for r in val_result.get("results", []) if not r["passed"]]

        if failed:
            try:
                svc.delete_draft(draft_id)
            except Exception:
                pass
            return {
                "ok": False,
                "stage": "validate",
                "error": (
                    f"{len(failed)} of {val_result.get('total', '?')} item(s) failed validation."
                ),
                "details": failed,
            }

        pub_result = svc.publish_draft(draft_id)
        if not pub_result.get("ok"):
            return {
                "ok": False,
                "stage": "publish",
                "error": pub_result.get("error", "publish_draft returned ok=False with no error message"),
                "details": pub_result,
            }

        return {"ok": True}

    except Exception as exc:
        return {
            "ok": False,
            "stage": "exception",
            "error": str(exc),
        }


def _delete_draft(context: CapabilityContext) -> dict[str, Any]:
    """Delete a draft and all its items."""
    draft_id = context.require("draft_id")
    svc = _get_draft_service()
    svc.delete_draft(draft_id)
    return {"deleted": True, "draft_id": draft_id}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="parse_function_blocks",
        pack_id=PACK_ID,
        version="1",
        display_name="Parse Function Blocks",
        description="Read a Cannibal output JSON file and return the list of extracted function source strings.",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("functions_json_path",),
            output=("blocks", "count"),
        ),
        implementation_logic=_parse_function_blocks,
        tags=("capability_intake",),
    ))

    registry.register(CapabilityDefinition(
        capability_id="parse_function_name",
        pack_id=PACK_ID,
        version="1",
        display_name="Parse Function Name",
        description="Return the name of the first function definition found in Python source text.",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("source",),
            output=("name",),
        ),
        implementation_logic=_parse_function_name,
        tags=("capability_intake",),
    ))

    registry.register(CapabilityDefinition(
        capability_id="compare_function_to_inventory",
        pack_id=PACK_ID,
        version="1",
        display_name="Compare Function to Inventory",
        description=(
            "Compare an incoming function source against all live installed capabilities. "
            "Returns comparison evidence including is_literal_duplicate flag."
        ),
        capability_type="function",
        contract=CapabilityContract(
            inputs=("source", "name"),
            output=("function_name", "comparisons", "is_literal_duplicate", "duplicate_target"),
        ),
        implementation_logic=_compare_function_to_inventory,
        tags=("capability_intake",),
    ))

    registry.register(CapabilityDefinition(
        capability_id="write_function_to_authored_module",
        pack_id=PACK_ID,
        version="1",
        display_name="Write Function to Authored Module",
        description=(
            "Write a function implementation to the platform-managed authored_capabilities module "
            "with collision-safe naming. Returns implementation_ref, capability_id, display_name."
        ),
        capability_type="function",
        contract=CapabilityContract(
            inputs=("source", "name"),
            output=("implementation_ref", "capability_id", "display_name"),
        ),
        implementation_logic=_write_function_to_authored_module,
        tags=("capability_intake",),
    ))

    registry.register(CapabilityDefinition(
        capability_id="record_comparison_evidence",
        pack_id=PACK_ID,
        version="1",
        display_name="Record Comparison Evidence",
        description="Persist comparison evidence rows for a Blacksmith run.",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("run_id", "evidence"),
            output=("evidence_ids", "count"),
        ),
        implementation_logic=_record_comparison_evidence,
        tags=("capability_intake",),
    ))

    registry.register(CapabilityDefinition(
        capability_id="create_capability_draft",
        pack_id=PACK_ID,
        version="1",
        display_name="Create Capability Draft",
        description="Create a new capability draft container. Returns draft_id.",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("name",),
            output=("draft_id",),
        ),
        implementation_logic=_create_capability_draft,
        tags=("capability_intake",),
    ))

    registry.register(CapabilityDefinition(
        capability_id="fill_draft_with_function",
        pack_id=PACK_ID,
        version="1",
        display_name="Fill Draft with Function",
        description=(
            "Add a base capability draft item to an existing draft. "
            "Supplies minimal honest draft_data: display_name, capability_type, pack_id, "
            "implementation_ref, code_block."
        ),
        capability_type="function",
        contract=CapabilityContract(
            inputs=("draft_id", "name", "capability_id", "code_block", "implementation_ref"),
            output=("item_id",),
        ),
        implementation_logic=_fill_draft_with_function,
        tags=("capability_intake",),
    ))

    registry.register(CapabilityDefinition(
        capability_id="validate_and_publish_draft",
        pack_id=PACK_ID,
        version="1",
        display_name="Validate and Publish Draft",
        description=(
            "Validate all items in a draft then publish atomically. "
            "Deletes the draft on validation failure — never leaves orphaned drafts."
        ),
        capability_type="function",
        contract=CapabilityContract(
            inputs=("draft_id",),
            output=("ok", "stage", "error", "details"),
        ),
        implementation_logic=_validate_and_publish_draft,
        tags=("capability_intake",),
    ))

    registry.register(CapabilityDefinition(
        capability_id="delete_draft",
        pack_id=PACK_ID,
        version="1",
        display_name="Delete Draft",
        description="Delete a capability draft and all its items.",
        capability_type="function",
        contract=CapabilityContract(
            inputs=("draft_id",),
            output=("deleted",),
        ),
        implementation_logic=_delete_draft,
        tags=("capability_intake",),
    ))
