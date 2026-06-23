import ast
import ast
import re
from dataclasses import dataclass
from collections import defaultdict
from pathlib import Path, PurePosixPath

from trevvos_forge.exceptions import DiffError
from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput
from trevvos_forge.operation_applier import apply_operation_change_to_content

IMPORT_ERROR_PREFIX = "Symbol `"
IMPORT_ERROR_SUFFIX = "` is used but not imported or defined."
SAFE_IMPORT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class SimpleImportInfo:
    path: str
    text: str
    names: list[ast.alias]


@dataclass(frozen=True)
class ImportInsertionPoint:
    path: str
    kind: str
    target_line: str
    needs_blank_line_before: bool
    needs_blank_line_after: bool


def validate_generated_test_structure(
    content: str,
    framework: str,
    test_file: str,
    source_symbols: list[str] | None = None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    discovered_tests: list[str] = []

    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return {
            "status": "failed",
            "framework": framework,
            "test_file": test_file,
            "errors": [f"SyntaxError in generated test file: {exc.msg} at line {exc.lineno}."],
            "warnings": [],
            "discovered_tests": [],
        }

    testcase_classes = _unittest_testcase_classes(tree)
    module_test_functions = [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test_name(node.name)
    ]
    test_methods = _test_methods_by_class(tree)
    nested_tests = _nested_test_functions(tree)

    for name in nested_tests:
        errors.append(f"Nested test function `{name}` will not be discovered.")

    if framework == "unittest":
        for node in module_test_functions:
            errors.append(
                f"Top-level pytest-style test function `{node.name}` is not discoverable by unittest discover."
            )

        if _imports_unittest(tree) and not testcase_classes:
            errors.append("Generated unittest test file imports unittest but has no unittest.TestCase class.")

        for class_node in testcase_classes:
            for method in test_methods.get(class_node.name, []):
                if not method.args.args or method.args.args[0].arg != "self":
                    errors.append(
                        f"unittest test method `{class_node.name}.{method.name}` must declare `self` as its first parameter."
                    )
                else:
                    discovered_tests.append(f"{class_node.name}.{method.name}")

        for node in ast.walk(tree):
            if _is_self_assert_call(node) and not _inside_unittest_method(tree, node, testcase_classes):
                errors.append("self.assert* is used outside a unittest.TestCase test method.")
                break

    elif framework == "pytest":
        for node in module_test_functions:
            discovered_tests.append(node.name)
            if _function_uses_self_assert(node):
                errors.append(f"Top-level pytest test function `{node.name}` uses self.assert*.")

        for class_name, methods in test_methods.items():
            if class_name in {class_node.name for class_node in testcase_classes}:
                warnings.append(f"pytest test file includes unittest.TestCase class `{class_name}`.")
                for method in methods:
                    discovered_tests.append(f"{class_name}.{method.name}")
            elif class_name.startswith("Test"):
                for method in methods:
                    discovered_tests.append(f"{class_name}.{method.name}")
    else:
        for node in module_test_functions:
            discovered_tests.append(node.name)
        for class_name, methods in test_methods.items():
            for method in methods:
                discovered_tests.append(f"{class_name}.{method.name}")

    if framework == "unittest" and not discovered_tests:
        errors.append("Generated unittest test file has no discoverable unittest.TestCase test methods.")
    elif framework != "unittest" and not discovered_tests:
        errors.append("Generated test file has no discoverable tests.")

    errors.extend(_missing_source_symbol_import_errors(tree, source_symbols or []))

    return {
        "status": "failed" if errors else "passed",
        "framework": framework,
        "test_file": test_file,
        "errors": errors,
        "warnings": warnings,
        "discovered_tests": discovered_tests,
    }


def validate_file_changes_test_structure(
    *,
    workspace_root: Path,
    file_changes: FileChangesOutput,
    framework: str,
    source_symbols: list[str] | None = None,
) -> dict:
    final_contents = compose_generated_test_contents(workspace_root=workspace_root, file_changes=file_changes)
    file_results = {
        path: validate_generated_test_structure(
            content=content,
            framework=framework,
            test_file=path,
            source_symbols=source_symbols,
        )
        for path, content in final_contents.items()
    }
    errors = [error for result in file_results.values() for error in result["errors"]]
    warnings = [warning for result in file_results.values() for warning in result["warnings"]]
    discovered_tests = [test for result in file_results.values() for test in result["discovered_tests"]]

    return {
        "status": "failed" if errors else "passed",
        "framework": framework,
        "errors": errors,
        "warnings": warnings,
        "discovered_tests": discovered_tests,
        "files": file_results,
}


def compose_generated_test_contents(*, workspace_root: Path, file_changes: FileChangesOutput) -> dict[str, str]:
    changes_by_path: dict[str, list] = defaultdict(list)

    for change in file_changes.changes:
        changes_by_path[_normalize_change_path(change.path)].append(change)

    final_contents: dict[str, str] = {}

    for normalized_path, changes in changes_by_path.items():
        target_path = (workspace_root / normalized_path).resolve()
        _ensure_inside_workspace(workspace_root.resolve(), target_path)
        original_content = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        current_content = original_content

        for change in changes:
            if change.mode == "full_file_rewrite":
                if change.content is None:
                    raise DiffError(f"full_file_rewrite change missing content for {change.path}")
                current_content = _ensure_final_newline(change.content)
                continue

            result = apply_operation_change_to_content(
                change=change,
                original_content=original_content,
                current_content=current_content,
                path=normalized_path,
            )
            current_content = result.new_content
            if original_content is None and change.operation == "create_file":
                original_content = None

        if current_content is None:
            raise DiffError(f"Could not compose generated test content for {normalized_path}")

        final_contents[normalized_path] = current_content

    return final_contents


def repair_missing_test_imports(
    *,
    content: str,
    test_file: str,
    source_module: str,
    missing_symbols: list[str],
    source_symbols: list[str],
) -> dict:
    missing_set = [symbol for symbol in dict.fromkeys(missing_symbols) if symbol in source_symbols]

    if not missing_set:
        return {
            "status": "not_repairable",
            "reason": "missing_symbol_not_in_source",
            "source_module": source_module,
            "symbols": sorted(set(missing_symbols)),
            "symbols_added": [],
        }

    if not SAFE_IMPORT_NAME_PATTERN.fullmatch(source_module):
        return {
            "status": "not_repairable",
            "reason": "unsafe_source_module",
            "source_module": source_module,
            "symbols": sorted(set(missing_set)),
            "symbols_added": [],
        }

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return {
            "status": "not_repairable",
            "reason": "syntax_error",
            "source_module": source_module,
            "symbols": sorted(set(missing_set)),
            "symbols_added": [],
        }

    simple_import = _find_simple_source_import(tree, source_module, test_file=test_file, content=content)
    ordered_symbols = sorted({*_existing_import_names(simple_import), *missing_set})
    import_line = f"from {source_module} import {', '.join(ordered_symbols)}"

    if simple_import is not None:
        original_line = simple_import.text
        repaired_content = content.replace(original_line, import_line, 1)
        return {
            "status": "repaired",
            "source_module": source_module,
            "symbols_added": sorted(set(missing_set)),
            "strategy": "updated_existing_from_import",
            "content": _ensure_final_newline(repaired_content),
            "change": {
                "path": simple_import.path,
                "change_type": "modified",
                "content": None,
                "mode": "operation_based_edit",
                "operation": "replace_exact_text",
                "target": original_line,
                "replacement": import_line,
            },
        }

    insertion = _find_import_insertion_point(tree=tree, content=content, test_file=test_file)
    if insertion is None:
        return {
            "status": "not_repairable",
            "reason": "no_safe_import_insertion_point",
            "source_module": source_module,
            "symbols": sorted(set(missing_set)),
            "symbols_added": [],
        }

    target_line = insertion.target_line
    import_insert = f"from {source_module} import {', '.join(ordered_symbols)}"

    if insertion.needs_blank_line_before:
        import_insert = "\n" + import_insert

    if insertion.needs_blank_line_after:
        import_insert = import_insert + "\n"

    repaired_content = content
    if insertion.kind == "after_line":
        repaired_content = _insert_after_line(repaired_content, target_line, import_insert)
    else:
        repaired_content = _insert_before_line(repaired_content, target_line, import_insert)

    return {
        "status": "repaired",
        "source_module": source_module,
        "symbols_added": sorted(set(missing_set)),
        "strategy": "inserted_new_from_import",
        "content": _ensure_final_newline(repaired_content),
        "change": {
            "path": insertion.path,
            "change_type": "modified",
            "content": None,
            "mode": "operation_based_edit",
            "operation": "insert_after_line" if insertion.kind == "after_line" else "insert_before_line",
            "target": target_line,
            "insert": import_insert,
        },
    }


def build_test_import_repair_payload(
    *,
    test_file: str,
    source_module: str,
    repair_results: list[dict],
) -> dict:
    repaired_results = [result for result in repair_results if result.get("status") == "repaired"]
    if not repaired_results:
        all_symbols = sorted(
            {
                symbol
                for result in repair_results
                for symbol in result.get("symbols", [])
            }
        )
        reason = repair_results[0].get("reason", "not_repairable") if repair_results else "not_repairable"
        return {
            "status": "not_repairable",
            "reason": reason,
            "source_module": source_module,
            "test_file": test_file,
            "symbols": all_symbols,
            "symbols_added": [],
        }

    symbols_added = sorted(
        {
            symbol
            for result in repaired_results
            for symbol in result.get("symbols_added", [])
        }
    )
    strategy = repaired_results[0].get("strategy", "updated_existing_from_import")
    return {
        "status": "repaired",
        "source_module": source_module,
        "test_file": test_file,
        "symbols_added": symbols_added,
        "strategy": strategy,
    }


def repair_unittest_method_indentation(*, content: str, test_file: str) -> dict:
    normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized_content.splitlines(keepends=True)
    method_starts = [index for index, line in enumerate(lines) if _unittest_method_header(line) is not None]

    if not method_starts:
        return {
            "status": "not_repairable",
            "reason": "no_unittest_test_methods",
            "test_file": test_file,
            "strategy": "normalize_unittest_method_indentation",
            "methods_repaired": [],
        }

    if any(line.strip() for line in lines[: method_starts[0]]):
        return {
            "status": "not_repairable",
            "reason": "complex_nested_structure",
            "test_file": test_file,
            "strategy": "normalize_unittest_method_indentation",
            "methods_repaired": [],
        }

    repaired_lines: list[str] = []
    methods_repaired: list[str] = []
    cursor = 0

    for index, start in enumerate(method_starts):
        end = method_starts[index + 1] if index + 1 < len(method_starts) else len(lines)
        repaired_lines.extend(lines[cursor:start])
        block_result = _normalize_unittest_method_block(lines=lines[start:end], test_file=test_file)

        if block_result is None:
            return {
                "status": "not_repairable",
                "reason": "complex_nested_structure",
                "test_file": test_file,
                "strategy": "normalize_unittest_method_indentation",
                "methods_repaired": [],
            }

        repaired_lines.extend(block_result["lines"])
        methods_repaired.extend(block_result["methods_repaired"])
        cursor = end

    if any(line.strip() for line in lines[cursor:]):
        return {
            "status": "not_repairable",
            "reason": "complex_nested_structure",
            "test_file": test_file,
            "strategy": "normalize_unittest_method_indentation",
            "methods_repaired": [],
        }

    repaired_lines.extend(lines[cursor:])

    return {
        "status": "repaired",
        "test_file": test_file,
        "strategy": "normalize_unittest_method_indentation",
        "methods_repaired": methods_repaired,
        "content": "".join(repaired_lines),
    }


def _is_test_name(name: str) -> bool:
    return name.startswith("test_") or name == "test"


def _normalize_unittest_method_block(*, lines: list[str], test_file: str) -> dict | None:
    if not lines:
        return None

    header = lines[0]
    match = _unittest_method_header(header)

    if match is None:
        return None

    header_indent = len(header) - len(header.lstrip(" "))
    method_name = match.group(2)
    delta = 4 - header_indent
    normalized_lines: list[str] = []

    for line in lines:
        if not line.strip():
            normalized_lines.append(line)
            continue

        if "\t" in line:
            return None

        leading_spaces = len(line) - len(line.lstrip(" "))
        if leading_spaces < header_indent and _unittest_method_header(line) is None:
            return None

        new_indent = leading_spaces + delta
        if new_indent < 0:
            return None

        normalized_lines.append((" " * new_indent) + line[leading_spaces:])

    return {
        "lines": normalized_lines,
        "methods_repaired": [method_name],
    }


def _unittest_method_header(line: str) -> re.Match[str] | None:
    return re.match(r"^([ ]*)def (test_[A-Za-z_][A-Za-z0-9_]*)\s*\(", line)


def _imports_unittest(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name == "unittest" for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "unittest":
            return True
    return False


def _unittest_testcase_classes(tree: ast.Module) -> list[ast.ClassDef]:
    return [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and any(_base_name(base) in {"unittest.TestCase", "TestCase"} for base in node.bases)
    ]


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _base_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _test_methods_by_class(tree: ast.Module) -> dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]:
    methods: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods[node.name] = [
            child
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test_name(child.name)
        ]

    return methods


def _nested_test_functions(tree: ast.Module) -> list[str]:
    nested: list[str] = []

    def visit_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_test_name(child.name):
                    nested.append(child.name)
                visit_function(child)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_function(node)

    return sorted(set(nested))


def _find_simple_source_import(
    tree: ast.Module,
    source_module: str,
    *,
    test_file: str,
    content: str,
) -> SimpleImportInfo | None:
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != source_module:
            continue
        if node.level != 0:
            continue
        if node.names and any(alias.asname for alias in node.names):
            return None
        if getattr(node, "end_lineno", node.lineno) != node.lineno:
            return None
        if any(alias.name == "*" for alias in node.names):
            return None

        return SimpleImportInfo(
            path=test_file,
            text=_line_text(content, node.lineno),
            names=list(node.names),
        )

    return None


def _existing_import_names(simple_import: SimpleImportInfo | None) -> set[str]:
    if simple_import is None:
        return set()
    return {alias.asname or alias.name for alias in simple_import.names}


def _find_import_insertion_point(*, tree: ast.Module, content: str, test_file: str) -> ImportInsertionPoint | None:
    docstring_end = 0
    insert_after_line = None
    insert_before_line = None

    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        docstring_end = getattr(tree.body[0], "end_lineno", tree.body[0].lineno)

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            insert_after_line = getattr(node, "end_lineno", node.lineno)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            insert_before_line = node.lineno
            break

    if insert_after_line is not None:
        return ImportInsertionPoint(
            path=test_file,
            kind="after_line",
            target_line=_line_text(content, insert_after_line),
            needs_blank_line_before=False,
            needs_blank_line_after=True,
        )

    if insert_before_line is not None:
        return ImportInsertionPoint(
            path=test_file,
            kind="before_line",
            target_line=_line_text(content, insert_before_line),
            needs_blank_line_before=docstring_end > 0,
            needs_blank_line_after=True,
        )

    return None


def _insert_after_line(content: str, target: str, insert: str) -> str:
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.rstrip("\r\n") == target.rstrip("\r\n"):
            insert_lines = _ensure_final_newline(insert).splitlines(keepends=True)
            return "".join(lines[: index + 1] + insert_lines + lines[index + 1 :])
    raise DiffError(f"Could not locate import insertion point: {target}")


def _insert_before_line(content: str, target: str, insert: str) -> str:
    lines = content.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.rstrip("\r\n") == target.rstrip("\r\n"):
            insert_lines = _ensure_final_newline(insert).splitlines(keepends=True)
            return "".join(lines[:index] + insert_lines + lines[index:])
    raise DiffError(f"Could not locate import insertion point: {target}")


def _line_text(content: str, line_number: int) -> str:
    lines = content.splitlines()
    if line_number <= 0 or line_number > len(lines):
        return ""
    return lines[line_number - 1]


def _is_self_assert_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr.startswith("assert")
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    )


def _function_uses_self_assert(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_is_self_assert_call(child) for child in ast.walk(node))


def _inside_unittest_method(tree: ast.Module, target: ast.AST, testcase_classes: list[ast.ClassDef]) -> bool:
    target_line = getattr(target, "lineno", -1)
    target_end = getattr(target, "end_lineno", target_line)

    for class_node in testcase_classes:
        for method in _test_methods_by_class(ast.Module(body=[class_node], type_ignores=[])).get(class_node.name, []):
            start = getattr(method, "lineno", -1)
            end = getattr(method, "end_lineno", start)
            if start <= target_line and target_end <= end:
                return True

    return False


def _missing_source_symbol_import_errors(tree: ast.Module, source_symbols: list[str]) -> list[str]:
    if not source_symbols:
        return []

    direct_names, imported_modules = _defined_or_imported_names(tree)
    used_direct_symbols: set[str] = set()
    used_attribute_symbols: dict[str, set[str]] = defaultdict(set)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in source_symbols:
            used_direct_symbols.add(node.func.id)
        elif isinstance(node.func, ast.Attribute) and node.func.attr in source_symbols:
            base = _base_name(node.func.value).split(".")[0]
            used_attribute_symbols[node.func.attr].add(base)

    errors: list[str] = []
    for symbol in sorted(used_direct_symbols):
        if symbol not in direct_names:
            errors.append(f"Symbol `{symbol}` is used but not imported or defined.")

    for symbol, bases in sorted(used_attribute_symbols.items()):
        if not any(base in imported_modules or base in direct_names for base in bases if base):
            errors.append(f"Symbol `{symbol}` is used as an attribute but its module is not imported or defined.")

    return errors


def _defined_or_imported_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    direct_names: set[str] = set()
    imported_modules: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                direct_names.add(name)
                imported_modules.add(name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                direct_names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            direct_names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                direct_names.update(_assigned_names(target))
        elif isinstance(node, ast.AnnAssign):
            direct_names.update(_assigned_names(node.target))

    return direct_names, imported_modules


def _assigned_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {name for element in node.elts for name in _assigned_names(element)}
    return set()


def _normalize_change_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/").lstrip("/")
    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]
    return str(PurePosixPath(normalized))


def _ensure_inside_workspace(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DiffError(f"Refusing to validate generated test outside workspace: {path}") from exc


def _ensure_final_newline(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized
