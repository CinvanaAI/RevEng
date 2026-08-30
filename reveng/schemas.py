from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ImportRecord:
    import_type: str
    module: str | None
    names: list[str]
    alias_map: dict[str, str]
    lineno: int | None
    end_lineno: int | None


@dataclass
class DecoratorRecord:
    text: str
    lineno: int | None
    end_lineno: int | None
    enclosing_scope: str


@dataclass
class AssignmentRecord:
    targets: list[str]
    value_type: str
    lineno: int | None
    end_lineno: int | None
    enclosing_scope: str
    value_repr: str = ""


@dataclass
class CallRecord:
    called_name: str
    lineno: int | None
    end_lineno: int | None
    enclosing_scope: str


@dataclass
class ReturnRecord:
    value_type: str
    lineno: int | None
    end_lineno: int | None
    enclosing_scope: str


@dataclass
class RaiseRecord:
    exception_type: str
    lineno: int | None
    end_lineno: int | None
    enclosing_scope: str


@dataclass
class ControlFlowRecord:
    node_type: str
    lineno: int | None
    end_lineno: int | None
    enclosing_scope: str


@dataclass
class StatementRecord:
    node_type: str
    lineno: int | None
    end_lineno: int | None
    enclosing_scope: str


@dataclass
class FunctionRecord:
    name: str
    function_type: str
    lineno: int | None
    end_lineno: int | None
    enclosing_scope: str
    decorators: list[DecoratorRecord] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    arg_annotations: dict[str, str] = field(default_factory=dict)


@dataclass
class ClassRecord:
    name: str
    lineno: int | None
    end_lineno: int | None
    enclosing_scope: str
    decorators: list[DecoratorRecord] = field(default_factory=list)
    methods: list[FunctionRecord] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)  # base class names from AST


@dataclass
class FileRecord:
    path: str
    module_name: str
    imports: list[ImportRecord] = field(default_factory=list)
    classes: list[ClassRecord] = field(default_factory=list)
    functions: list[FunctionRecord] = field(default_factory=list)
    top_level_statements: list[StatementRecord] = field(default_factory=list)
    calls: list[CallRecord] = field(default_factory=list)
    assignments: list[AssignmentRecord] = field(default_factory=list)
    returns: list[ReturnRecord] = field(default_factory=list)
    raises: list[RaiseRecord] = field(default_factory=list)
    control_flow: list[ControlFlowRecord] = field(default_factory=list)
    decorators: list[DecoratorRecord] = field(default_factory=list)
    main_block_present: bool = False


def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value