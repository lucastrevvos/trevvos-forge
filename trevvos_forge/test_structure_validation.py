import ast
from collections import defaultdict
from pathlib import Path, PurePosixPath

from trevvos_forge.exceptions import DiffError
from trevvos_forge.file_change_outputs import FileChangesOutput
from trevvos_forge.operation_applier import apply_operation_change_to_content


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
    final_contents = _compose_final_test_contents(workspace_root=workspace_root, file_changes=file_changes)
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


def _compose_final_test_contents(*, workspace_root: Path, file_changes: FileChangesOutput) -> dict[str, str]:
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


def _is_test_name(name: str) -> bool:
    return name.startswith("test_") or name == "test"


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
