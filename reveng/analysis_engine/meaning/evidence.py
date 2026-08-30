"""Evidence artifact TypedDicts for RevEng meaning extraction.

These types describe the expected shape of data produced by the deterministic
builder pipeline and consumed by Task Agents. They make the evidence contract
explicit without requiring a full rewrite of the data pipeline.

Relationship to reveng/schemas.py:
  FileRecord, CallRecord, ImportRecord — typed AST-level dataclasses in schemas.py
  are the ground truth for what defined_symbols, calls[], and imports[] entries
  look like at the AST level. The types here (EnrichedCallRecord, EnrichedImportRecord)
  describe the *enriched* wrappers that Task Agents actually receive after enrichment
  packs have run. They are distinct types with distinct names to avoid the naming
  collision between the AST layer (schemas.py) and the enriched layer (this file).
"""
from __future__ import annotations

from typing import Any, TypedDict


class SymbolRecord(TypedDict, total=False):
    """A function/method/class entry from enriched_file_breakdowns defined_symbols."""
    name: str
    symbol_type: str          # "function", "method", "async_function", "class"
    lineno: int
    end_lineno: int
    enclosing_scope: str      # e.g. "module > function:process"
    decorators: list[str]


class EnrichedCallRecord(TypedDict, total=False):
    """A call site entry from enriched_file_breakdowns calls[].

    Distinct from schemas.CallRecord (AST-level dataclass). This is the enriched
    wrapper shape seen by Task Agents after the enrichment pack has run.
    """
    callee: str
    lineno: int
    enclosing_scope: str      # same format as SymbolRecord.enclosing_scope
    call_type: str            # "direct", "method", "super", etc.


class EnrichedImportRecord(TypedDict, total=False):
    """An import entry from enriched_file_breakdowns imports[].

    Distinct from schemas.ImportRecord (AST-level dataclass). This is the enriched
    wrapper shape seen by Task Agents after the enrichment pack has run.
    """
    module: str
    names: list[str]
    lineno: int
    is_from: bool


class EnrichedFileRecord(TypedDict, total=False):
    """A single file entry in enriched_file_breakdowns (as produced by the enrichment pack).

    The top-level dict keyed by file_path maps to entries of this shape.
    See reveng/schemas.py FileRecord for the pre-enrichment AST-level type.
    """
    file_path: str
    defined_symbols: list[SymbolRecord]
    calls: list[EnrichedCallRecord]
    imports: list[EnrichedImportRecord]
    parse_error: str          # present only if the file could not be parsed


class ClusterRecord(TypedDict, total=False):
    """A single cluster entry in cluster_map.clusters[] (as produced by the clustering pack)."""
    cluster_id: str
    observed: _ClusterObserved
    derived: _ClusterDerived


class _ClusterObserved(TypedDict, total=False):
    files: list[str]          # file_paths in this cluster


class _ClusterDerived(TypedDict, total=False):
    cluster_type: str         # e.g. "utility", "core", "test"


class FlowRecord(TypedDict, total=False):
    """A single flow entry in flow_map.flows[] (as produced by the flow analysis pack)."""
    flow_id: str
    root_file: str            # entry point file path
    root_node_id: str         # node_id of the entry function
    observed: _FlowObserved
    derived: dict[str, Any]


class _FlowObserved(TypedDict, total=False):
    direct_callees: list[str]  # node_ids of directly reachable functions
