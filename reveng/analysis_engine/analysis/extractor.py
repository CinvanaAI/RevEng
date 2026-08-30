from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

from reveng.analysis_engine.analysis.scanner import iter_python_files
from reveng.schemas import (
    AssignmentRecord,
    CallRecord,
    ClassRecord,
    ControlFlowRecord,
    DecoratorRecord,
    FileRecord,
    FunctionRecord,
    ImportRecord,
    RaiseRecord,
    ReturnRecord,
    StatementRecord,
    to_dict,
)


def module_name_from_path(repo_root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(repo_root)
    parts = list(rel.parts)

    if len(parts) == 1 and parts[0] == "__init__.py":
        return "__root__"

    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]

    module_name = ".".join(parts)
    return module_name or "__root__"


def safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return "None"
    try:
        return ast.unparse(node)
    except Exception:
        return ast.dump(node, annotate_fields=False)


def get_call_name(node: ast.AST) -> str:
    text = safe_unparse(node)
    return " ".join(text.split())


def get_target_names(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in node.elts:
            names.extend(get_target_names(elt))
        return names

    text = safe_unparse(node).strip()
    return [text] if text else []


def get_arg_annotations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
    """Return {param_name: annotation_text} for each annotated parameter."""
    annotations: dict[str, str] = {}
    for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
        if arg.annotation is not None:
            try:
                annotations[arg.arg] = safe_unparse(arg.annotation)
            except Exception:
                pass
    return annotations


def get_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args: list[str] = []

    for arg in node.args.posonlyargs:
        args.append(arg.arg)
    for arg in node.args.args:
        args.append(arg.arg)
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    for arg in node.args.kwonlyargs:
        args.append(arg.arg)
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")

    return args


def decorator_records(
    decorator_list: list[ast.expr],
    enclosing_scope: str,
) -> list[DecoratorRecord]:
    results: list[DecoratorRecord] = []
    for dec in decorator_list:
        results.append(
            DecoratorRecord(
                text=safe_unparse(dec),
                lineno=getattr(dec, "lineno", None),
                end_lineno=getattr(dec, "end_lineno", None),
                enclosing_scope=enclosing_scope,
            )
        )
    return results


def is_main_block(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False
    if not isinstance(test.left, ast.Name) or test.left.id != "__name__":
        return False

    comparator = test.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value == "__main__"


class FileExtractor(ast.NodeVisitor):
    TOP_LEVEL_STATEMENT_TYPES = {
        "Assign",
        "AnnAssign",
        "AugAssign",
        "Expr",
        "Pass",
        "If",
        "For",
        "AsyncFor",
        "While",
        "Try",
        "With",
        "AsyncWith",
        "Match",
        "Return",
        "Raise",
        "Import",
        "ImportFrom",
    }

    def __init__(self) -> None:
        self.imports: list[ImportRecord] = []
        self.classes: list[ClassRecord] = []
        self.functions: list[FunctionRecord] = []
        self.top_level_statements: list[StatementRecord] = []
        self.calls: list[CallRecord] = []
        self.assignments: list[AssignmentRecord] = []
        self.returns: list[ReturnRecord] = []
        self.raises: list[RaiseRecord] = []
        self.control_flow: list[ControlFlowRecord] = []
        self.decorators: list[DecoratorRecord] = []
        self.main_block_present: bool = False

        self.scope_stack: list[str] = ["module"]

    @property
    def current_scope(self) -> str:
        return self.scope_stack[-1]

    def push_scope(self, value: str) -> None:
        self.scope_stack.append(value)

    def pop_scope(self) -> None:
        self.scope_stack.pop()

    def record_top_level_statement(self, node: ast.AST) -> None:
        if self.current_scope == "module" and type(node).__name__ in self.TOP_LEVEL_STATEMENT_TYPES:
            self.top_level_statements.append(
                StatementRecord(
                    node_type=type(node).__name__,
                    lineno=getattr(node, "lineno", None),
                    end_lineno=getattr(node, "end_lineno", None),
                    enclosing_scope=self.current_scope,
                )
            )

    def visit_Module(self, node: ast.Module) -> None:
        for child in node.body:
            self.visit(child)

    def visit_Import(self, node: ast.Import) -> None:
        self.record_top_level_statement(node)

        alias_map = {}
        names = []
        for alias in node.names:
            names.append(alias.name)
            if alias.asname:
                alias_map[alias.name] = alias.asname

        self.imports.append(
            ImportRecord(
                import_type="import",
                module=None,
                names=names,
                alias_map=alias_map,
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
            )
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.record_top_level_statement(node)

        alias_map = {}
        names = []
        for alias in node.names:
            names.append(alias.name)
            if alias.asname:
                alias_map[alias.name] = alias.asname

        module_text = "." * node.level + (node.module or "")

        self.imports.append(
            ImportRecord(
                import_type="from_import",
                module=module_text,
                names=names,
                alias_map=alias_map,
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_scope = f"{self.current_scope} > class:{node.name}"
        class_decorators = decorator_records(node.decorator_list, self.current_scope)
        self.decorators.extend(class_decorators)

        # Extract base class names from AST (for class hierarchy evidence)
        base_names: list[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(f"{ast.unparse(base)}")

        class_record = ClassRecord(
            name=node.name,
            lineno=getattr(node, "lineno", None),
            end_lineno=getattr(node, "end_lineno", None),
            enclosing_scope=self.current_scope,
            decorators=class_decorators,
            methods=[],
            bases=base_names,
        )

        self.classes.append(class_record)

        self.push_scope(class_scope)
        for child in node.body:
            if isinstance(child, ast.FunctionDef):
                method_scope = self.current_scope
                method_decorators = decorator_records(child.decorator_list, method_scope)
                self.decorators.extend(method_decorators)

                class_record.methods.append(
                    FunctionRecord(
                        name=child.name,
                        function_type="method",
                        lineno=getattr(child, "lineno", None),
                        end_lineno=getattr(child, "end_lineno", None),
                        enclosing_scope=method_scope,
                        decorators=method_decorators,
                        args=get_args(child),
                        arg_annotations=get_arg_annotations(child),
                    )
                )
                self._visit_function_body(child, child.name)
            elif isinstance(child, ast.AsyncFunctionDef):
                method_scope = self.current_scope
                method_decorators = decorator_records(child.decorator_list, method_scope)
                self.decorators.extend(method_decorators)

                class_record.methods.append(
                    FunctionRecord(
                        name=child.name,
                        function_type="async_method",
                        lineno=getattr(child, "lineno", None),
                        end_lineno=getattr(child, "end_lineno", None),
                        enclosing_scope=method_scope,
                        decorators=method_decorators,
                        args=get_args(child),
                        arg_annotations=get_arg_annotations(child),
                    )
                )
                self._visit_function_body(child, child.name)
            else:
                self.visit(child)
        self.pop_scope()

    def _visit_function_body(self, node: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> None:
        self.push_scope(f"{self.current_scope} > function:{name}")
        for child in node.body:
            self.visit(child)
        self.pop_scope()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        fn_scope = self.current_scope
        fn_decorators = decorator_records(node.decorator_list, fn_scope)
        self.decorators.extend(fn_decorators)

        self.functions.append(
            FunctionRecord(
                name=node.name,
                function_type="function" if self.current_scope == "module" else "nested_function",
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
                enclosing_scope=fn_scope,
                decorators=fn_decorators,
                args=get_args(node),
                arg_annotations=get_arg_annotations(node),
            )
        )

        self._visit_function_body(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        fn_scope = self.current_scope
        fn_decorators = decorator_records(node.decorator_list, fn_scope)
        self.decorators.extend(fn_decorators)

        self.functions.append(
            FunctionRecord(
                name=node.name,
                function_type="async_function" if self.current_scope == "module" else "nested_async_function",
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
                enclosing_scope=fn_scope,
                decorators=fn_decorators,
                args=get_args(node),
                arg_annotations=get_arg_annotations(node),
            )
        )

        self._visit_function_body(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(
            CallRecord(
                called_name=get_call_name(node.func),
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
                enclosing_scope=self.current_scope,
            )
        )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.record_top_level_statement(node)

        targets: list[str] = []
        for target in node.targets:
            targets.extend(get_target_names(target))

        self.assignments.append(
            AssignmentRecord(
                targets=targets,
                value_type=type(node.value).__name__,
                value_repr=safe_unparse(node.value),
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
                enclosing_scope=self.current_scope,
            )
        )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.record_top_level_statement(node)

        targets = get_target_names(node.target)
        value_type = type(node.value).__name__ if node.value is not None else "None"

        self.assignments.append(
            AssignmentRecord(
                targets=targets,
                value_type=value_type,
                value_repr=safe_unparse(node.value) if node.value is not None else "",
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
                enclosing_scope=self.current_scope,
            )
        )
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.record_top_level_statement(node)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self.record_top_level_statement(node)

        value_type = type(node.value).__name__ if node.value is not None else "None"
        self.returns.append(
            ReturnRecord(
                value_type=value_type,
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
                enclosing_scope=self.current_scope,
            )
        )
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.record_top_level_statement(node)

        exception_type = safe_unparse(node.exc) if node.exc is not None else "None"
        self.raises.append(
            RaiseRecord(
                exception_type=exception_type,
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
                enclosing_scope=self.current_scope,
            )
        )
        self.generic_visit(node)

    def _record_control_flow(self, node: ast.AST, node_type: str) -> None:
        self.record_top_level_statement(node)
        self.control_flow.append(
            ControlFlowRecord(
                node_type=node_type,
                lineno=getattr(node, "lineno", None),
                end_lineno=getattr(node, "end_lineno", None),
                enclosing_scope=self.current_scope,
            )
        )

    def visit_If(self, node: ast.If) -> None:
        if self.current_scope == "module" and is_main_block(node):
            self.main_block_present = True

        self._record_control_flow(node, "If")
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._record_control_flow(node, "For")
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._record_control_flow(node, "AsyncFor")
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._record_control_flow(node, "While")
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._record_control_flow(node, "Try")
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self._record_control_flow(node, "With")
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._record_control_flow(node, "AsyncWith")
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self._record_control_flow(node, "Match")
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        self.record_top_level_statement(node)
        self.generic_visit(node)

    def visit_Pass(self, node: ast.Pass) -> None:
        self.record_top_level_statement(node)
        self.generic_visit(node)


def extract_file_record(repo_root: Path, file_path: Path) -> dict:
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    extractor = FileExtractor()
    extractor.visit(tree)

    rel_path = file_path.relative_to(repo_root).as_posix()

    record = FileRecord(
        path=rel_path,
        module_name=module_name_from_path(repo_root, file_path),
        imports=extractor.imports,
        classes=extractor.classes,
        functions=extractor.functions,
        top_level_statements=extractor.top_level_statements,
        calls=extractor.calls,
        assignments=extractor.assignments,
        returns=extractor.returns,
        raises=extractor.raises,
        control_flow=extractor.control_flow,
        decorators=extractor.decorators,
        main_block_present=extractor.main_block_present,
    )
    return to_dict(record)


def extract_repo_inventory(repo_root: Path) -> dict:
    files = []
    python_files = sorted(iter_python_files(repo_root))

    for file_path in python_files:
        try:
            files.append(extract_file_record(repo_root, file_path))
        except SyntaxError as exc:
            rel_path = file_path.relative_to(repo_root).as_posix()
            files.append(
                {
                    "path": rel_path,
                    "module_name": module_name_from_path(repo_root, file_path),
                    "parse_error": f"SyntaxError: {exc}",
                }
            )

    return {
        "repo_root": str(repo_root),
        "scanned_at": datetime.now(UTC).isoformat(),
        "file_count": len(python_files),
        "files": files,
    }
