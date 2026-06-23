import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from trevvos_forge.config_store import load_config
from trevvos_forge.exceptions import DiffError, WorkspaceError
from trevvos_forge.file_change_outputs import FileChangesOutput


TEST_FILE_ERROR = "Test file must be inside a tests directory or match test_*.py / *_test.py."
SAFE_PYTEST_SYMBOL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class SymbolInfo:
    name: str
    kind: str
    line: int


@dataclass(frozen=True)
class TestGenerationTarget:
    source_path: str
    source_module: str
    symbol: SymbolInfo | None
    symbols: list[SymbolInfo]
    all_symbols: bool
    test_file: str
    test_file_exists: bool
    framework: str
    suggested_test_command: str


@dataclass(frozen=True)
class ExistingTestsCheck:
    status: str
    test_file: str
    mode: str
    symbols_requested: list[str]
    symbols_covered: list[str]
    symbols_missing: list[str]
    symbols: dict[str, dict]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "test_file": self.test_file,
            "mode": self.mode,
            "symbols_requested": self.symbols_requested,
            "symbols_covered": self.symbols_covered,
            "symbols_missing": self.symbols_missing,
            "symbols": self.symbols,
        }


def validate_python_symbol(source_file: Path, symbol: str) -> SymbolInfo:
    try:
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        raise WorkspaceError(f"Cannot parse Python source file: {source_file.name}") from exc

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            return SymbolInfo(name=node.name, kind=kind, line=node.lineno)

    raise WorkspaceError(f"Symbol `{symbol}` not found in {source_file.name}.")


def detect_testable_python_symbols(source_file: Path) -> list[SymbolInfo]:
    try:
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        raise WorkspaceError(f"Cannot parse Python source file: {source_file.name}") from exc

    symbols: list[SymbolInfo] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name.startswith("_"):
            continue
        if node.name == "main":
            continue

        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        symbols.append(SymbolInfo(name=node.name, kind=kind, line=node.lineno))

    if not symbols:
        raise WorkspaceError(f"No public testable symbols found in {source_file.name}.")

    return symbols


def build_test_generation_target(
    *,
    workspace_root: Path,
    source_path: Path,
    symbol: str | None,
    all_symbols: bool = False,
    requested_test_file: Path | None = None,
    e2e: bool = False,
) -> TestGenerationTarget:
    if e2e:
        raise WorkspaceError("E2E test generation is not implemented in this MVP. Use --unit.")

    root = workspace_root.resolve()
    source_file = (root / source_path).resolve()
    _ensure_inside_workspace(root, source_file)

    if not source_file.exists() or not source_file.is_file():
        raise WorkspaceError(f"Source file not found: {_relative_posix(root, source_file)}")

    if source_file.suffix != ".py":
        raise WorkspaceError("MVP test generation currently supports Python source files only.")

    if all_symbols:
        symbol_info = None
        symbols = detect_testable_python_symbols(source_file)
    elif symbol is not None:
        symbol_info = validate_python_symbol(source_file, symbol)
        symbols = [symbol_info]
    else:
        raise WorkspaceError("Specify --symbol <name> or --all.")

    source_relative = _relative_posix(root, source_file)
    source_module = _python_module_name(source_relative)

    if requested_test_file is not None:
        test_file = normalize_workspace_path(root, requested_test_file)
        validate_test_file_path(test_file)
    else:
        test_file = detect_test_file(workspace_root=root, source_relative=source_relative)

    test_file_exists = (root / test_file).exists()
    framework = detect_test_framework(workspace_root=root, test_file=test_file)
    test_command = "pytest" if framework == "pytest" else "python -m unittest discover -s tests"

    return TestGenerationTarget(
        source_path=source_relative,
        source_module=source_module,
        symbol=symbol_info,
        symbols=symbols,
        all_symbols=all_symbols,
        test_file=test_file,
        test_file_exists=test_file_exists,
        framework=framework,
        suggested_test_command=test_command,
    )


def target_with_symbols(target: TestGenerationTarget, symbols: list[SymbolInfo]) -> TestGenerationTarget:
    return TestGenerationTarget(
        source_path=target.source_path,
        source_module=target.source_module,
        symbol=target.symbol if not target.all_symbols else None,
        symbols=symbols,
        all_symbols=target.all_symbols,
        test_file=target.test_file,
        test_file_exists=target.test_file_exists,
        framework=target.framework,
        suggested_test_command=target.suggested_test_command,
    )


def detect_test_file(*, workspace_root: Path, source_relative: str) -> str:
    module_name = PurePosixPath(source_relative).stem
    candidates = [
        f"tests/test_{module_name}.py",
        f"test_{module_name}.py",
        f"tests/{module_name}_test.py",
    ]

    for candidate in candidates:
        if (workspace_root / candidate).exists():
            return candidate

    return candidates[0]


def detect_test_framework(*, workspace_root: Path, test_file: str) -> str:
    test_path = workspace_root / test_file

    if test_path.exists():
        try:
            content = test_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = ""
        if "unittest.TestCase" in content or "import unittest" in content:
            return "unittest"
        if "import pytest" in content or "pytest." in content:
            return "pytest"

    if (workspace_root / "pytest.ini").exists():
        return "pytest"

    pyproject = workspace_root / "pyproject.toml"
    if pyproject.exists():
        try:
            pyproject_text = pyproject.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            pyproject_text = ""
        if "pytest" in pyproject_text:
            return "pytest"

    for path in list((workspace_root / "tests").glob("test_*.py"))[:50] if (workspace_root / "tests").exists() else []:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "unittest.TestCase" in content or "import unittest" in content:
            return "unittest"
        if "import pytest" in content or "pytest." in content:
            return "pytest"

    return "unittest"


def validate_test_file_path(path: str) -> None:
    pure_path = PurePosixPath(path)

    if pure_path.is_absolute() or ".." in pure_path.parts or not pure_path.name:
        raise WorkspaceError(TEST_FILE_ERROR)

    if pure_path.suffix != ".py":
        raise WorkspaceError(TEST_FILE_ERROR)

    if "conftest.py" == pure_path.name:
        raise WorkspaceError("Modifying conftest.py is not supported in the MVP.")

    if "tests" in pure_path.parts or "test" in pure_path.parts:
        return

    if pure_path.name.startswith("test_") or pure_path.name.endswith("_test.py"):
        return

    raise WorkspaceError(TEST_FILE_ERROR)


def validate_file_changes_are_tests_only(file_changes: FileChangesOutput) -> None:
    for change in file_changes.changes:
        path = normalize_change_path(change.path)
        validate_test_file_path(path)

        if change.mode == "full_file_rewrite" and change.change_type == "modified":
            raise DiffError(
                f"Test generation rejected: full_file_rewrite is not allowed for existing test file: {path}"
            )


def build_existing_tests_check(
    *,
    target: TestGenerationTarget,
    test_file_content: str | None,
) -> ExistingTestsCheck:
    requested = [symbol.name for symbol in target.symbols]
    mode = "all_symbols" if target.all_symbols else "single_symbol"

    if test_file_content is None:
        symbols = {name: {"covered": False, "evidence": []} for name in requested}
        return ExistingTestsCheck(
            status="not_applicable",
            test_file=target.test_file,
            mode=mode,
            symbols_requested=requested,
            symbols_covered=[],
            symbols_missing=requested,
            symbols=symbols,
        )

    symbols = detect_existing_tests_for_symbols(
        test_file_content=test_file_content,
        symbols=requested,
        framework=target.framework,
    )
    covered = [name for name in requested if symbols[name]["covered"]]
    missing = [name for name in requested if not symbols[name]["covered"]]

    if not covered:
        status = "none"
    elif not missing:
        status = "all_covered"
    else:
        status = "partial"

    return ExistingTestsCheck(
        status=status,
        test_file=target.test_file,
        mode=mode,
        symbols_requested=requested,
        symbols_covered=covered,
        symbols_missing=missing,
        symbols=symbols,
    )


def detect_existing_tests_for_symbols(
    *,
    test_file_content: str,
    symbols: list[str],
    framework: str | None = None,
) -> dict[str, dict]:
    del framework
    result = {symbol: {"covered": False, "evidence": []} for symbol in symbols}

    try:
        tree = ast.parse(test_file_content)
    except SyntaxError:
        return _detect_existing_tests_with_regex(test_file_content, symbols)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue

        lower_test_name = node.name.lower()
        called_names = _called_names(node)

        for symbol in symbols:
            lower_symbol = symbol.lower()
            if lower_symbol in lower_test_name:
                _add_symbol_evidence(result, symbol, node.name)
            if symbol in called_names:
                _add_symbol_evidence(result, symbol, f"calls {symbol}")

    return result


def _detect_existing_tests_with_regex(test_file_content: str, symbols: list[str]) -> dict[str, dict]:
    result = {symbol: {"covered": False, "evidence": []} for symbol in symbols}

    for symbol in symbols:
        escaped = re.escape(symbol)
        test_match = re.search(rf"def\s+(test_\w*{escaped}\w*)\s*\(", test_file_content, re.IGNORECASE)
        if test_match:
            _add_symbol_evidence(result, symbol, test_match.group(1))

        if re.search(rf"(?<![\w.]){escaped}\s*\(", test_file_content) or re.search(
            rf"\.{escaped}\s*\(",
            test_file_content,
        ):
            _add_symbol_evidence(result, symbol, f"calls {symbol}")

    return result


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        if isinstance(child.func, ast.Name):
            names.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)

    return names


def _add_symbol_evidence(result: dict[str, dict], symbol: str, evidence: str) -> None:
    result[symbol]["covered"] = True
    if evidence not in result[symbol]["evidence"]:
        result[symbol]["evidence"].append(evidence)


def normalize_change_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/").lstrip("/")
    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]
    return str(PurePosixPath(normalized))


def normalize_workspace_path(workspace_root: Path, path: Path) -> str:
    root = workspace_root.resolve()
    resolved = (root / path).resolve()
    _ensure_inside_workspace(root, resolved)
    return _relative_posix(root, resolved)


def build_selected_files_payload(target: TestGenerationTarget, test_file_size: int = 0) -> dict:
    selected_files = [
        {"path": target.source_path, "reason": "source under test", "total_lines": 0},
    ]
    if target.test_file_exists:
        selected_files.append(
            {"path": target.test_file, "reason": "test destination", "total_lines": test_file_size}
        )
    return {"selected_files": selected_files}


def build_test_generation_context(
    *,
    workspace_root: Path,
    target: TestGenerationTarget,
    source_content: str,
    test_content: str | None,
    existing_tests_check: ExistingTestsCheck | None = None,
    force: bool = False,
) -> str:
    existing_test = test_content if test_content is not None else "(test file does not exist yet)"
    mode = "all_symbols" if target.all_symbols else "single_symbol"
    requested_symbol = target.symbol.name if target.symbol is not None else "(all)"
    symbol_kind = target.symbol.kind if target.symbol is not None else "(multiple)"
    symbol_line = str(target.symbol.line) if target.symbol is not None else "(multiple)"
    symbols_to_test = "\n".join(f"- {symbol.name}" for symbol in target.symbols)
    existing_tests_section = _existing_tests_prompt_section(existing_tests_check, force)
    return f"""Source file: {target.source_path}
Source module: {target.source_module}
Mode: {mode}
Requested symbol: {requested_symbol}
Symbol kind: {symbol_kind}
Symbol line: {symbol_line}
Symbols to test:
{symbols_to_test}
Target test file: {target.test_file}
Target test file exists: {str(target.test_file_exists).lower()}
Detected framework: {target.framework}
Suggested test command: {target.suggested_test_command}
Workspace root: {workspace_root}

Source content:
```python
{source_content}
```

Existing target test content:
```python
{existing_test}
```

Existing tests analysis:
{existing_tests_section}"""


def build_test_generation_summary(
    *,
    target: TestGenerationTarget,
    files_changed: list[str],
    write: bool,
    status: str,
    existing_tests_check: ExistingTestsCheck | None = None,
    generation_retries: dict | None = None,
    sandbox_retries: dict | None = None,
    structure_validation: dict | None = None,
    unittest_method_repair: dict | None = None,
    import_repair: dict | None = None,
    structure_retries: dict | None = None,
) -> str:
    changed = "\n".join(f"- {path}" for path in files_changed) or "- none"
    symbol = target.symbol.name if target.symbol is not None else "all"
    symbols_targeted = "\n".join(f"- {symbol.name}" for symbol in target.symbols)
    existing_tests_summary = _existing_tests_summary_section(existing_tests_check)
    generation_retry_summary = _generation_retry_summary_section(generation_retries)
    sandbox_retry_summary = _sandbox_retry_summary_section(sandbox_retries)
    structure_summary = _structure_validation_summary_section(structure_validation)
    unittest_method_repair_summary = _unittest_method_repair_summary_section(unittest_method_repair)
    import_repair_summary = _import_repair_summary_section(import_repair)
    structure_retry_summary = _structure_retry_summary_section(structure_retries)
    return f"""# Test Generation Summary

Mode: controlled_execution
Command: tests add
Source: {target.source_path}
Symbol: {symbol}
Target test file: {target.test_file}
Framework: {target.framework}
Write: {str(write).lower()}
Status: {status}

## Symbols targeted

{symbols_targeted}

## Existing tests

{existing_tests_summary}

## Test generation schema retry

{generation_retry_summary}

## Sandbox retry

{sandbox_retry_summary}

## Test structure validation

{structure_summary}

## Unittest method repair

{unittest_method_repair_summary}

## Test import repair

{import_repair_summary}

## Structure retry

{structure_retry_summary}

Files changed:
{changed}

Safety:
- Controlled Execution: test files only.
- Production source files were not accepted as patch targets.
"""


def metadata_for_target(
    *,
    target: TestGenerationTarget,
    write: bool,
    prompt_ref: str,
    status: str,
    files_changed: list[str],
    sandbox_status: str | None = None,
    sandbox_commands: list[str] | None = None,
    sandbox_command_source: str | None = None,
    symbol_selector: dict | None = None,
    existing_tests_check: ExistingTestsCheck | None = None,
    generation_retries: dict | None = None,
    sandbox_retries: dict | None = None,
    structure_validation: dict | None = None,
    unittest_method_repair: dict | None = None,
    import_repair: dict | None = None,
    structure_retries: dict | None = None,
    symbols_original: list[str] | None = None,
    provider_called: bool | None = None,
    write_allowed: bool | None = None,
) -> dict:
    metadata = {
        "mode": "controlled_execution",
        "command": "tests add",
        "source_path": target.source_path,
        "symbol": target.symbol.name if target.symbol is not None else None,
        "all": target.all_symbols,
        "symbols": [symbol.name for symbol in target.symbols],
        "test_file": target.test_file,
        "write": write,
        "prompt": prompt_ref,
        "status": status,
        "files_changed": files_changed,
        "framework": target.framework,
        "test_type": "unit",
    }

    if symbols_original is not None:
        metadata["symbols_original"] = symbols_original

    if existing_tests_check is not None:
        metadata["existing_tests"] = {
            "status": existing_tests_check.status,
            "symbols_covered": existing_tests_check.symbols_covered,
            "symbols_missing": existing_tests_check.symbols_missing,
        }

    if generation_retries is not None:
        metadata["generation_retries"] = {
            "max": generation_retries.get("max"),
            "used": generation_retries.get("used"),
            "status": generation_retries.get("status"),
        }

    if sandbox_retries is not None:
        metadata["sandbox_retries"] = {
            "max": sandbox_retries.get("max"),
            "used": sandbox_retries.get("used"),
            "status": sandbox_retries.get("status"),
        }

    if structure_validation is not None:
        metadata["test_structure_validation"] = {
            "status": structure_validation.get("status"),
            "errors": structure_validation.get("errors", []),
            "warnings": structure_validation.get("warnings", []),
            "discovered_tests": structure_validation.get("discovered_tests", []),
        }

    if unittest_method_repair is not None:
        metadata["test_unittest_method_repair"] = {
            "status": unittest_method_repair.get("status"),
            "test_file": unittest_method_repair.get("test_file"),
            "strategy": unittest_method_repair.get("strategy"),
            "methods_repaired": unittest_method_repair.get("methods_repaired", []),
            "reason": unittest_method_repair.get("reason"),
        }

    if import_repair is not None:
        metadata["test_import_repair"] = {
            "status": import_repair.get("status"),
            "symbols_added": import_repair.get("symbols_added", []),
            "strategy": import_repair.get("strategy"),
            "reason": import_repair.get("reason"),
        }

    if structure_retries is not None:
        metadata["structure_retries"] = {
            "max": structure_retries.get("max"),
            "used": structure_retries.get("used"),
            "status": structure_retries.get("status"),
        }

    if provider_called is not None:
        metadata["provider_called"] = provider_called

    if sandbox_status is not None:
        metadata["sandbox"] = {
            "enabled": True,
            "status": sandbox_status,
            "commands": sandbox_commands or [],
        }
        if sandbox_command_source is not None:
            metadata["sandbox"]["command_source"] = sandbox_command_source
        if symbol_selector is not None:
            metadata["sandbox"]["symbol_selector"] = symbol_selector

    if write_allowed is not None:
        metadata["write_allowed"] = write_allowed

    return metadata


def select_test_generation_commands(*, workspace_root: Path, target: TestGenerationTarget) -> tuple[list[str], str, dict]:
    config = load_config(workspace_root)
    configured = config.get("test_commands")

    if isinstance(configured, list):
        commands = [command.strip() for command in configured if isinstance(command, str) and command.strip()]
        if commands:
            return commands, "config", _disabled_symbol_selector("config_override")

    if target.framework == "pytest":
        pytest_command = _pytest_target_command(target.test_file)
        if pytest_command is not None:
            selector = _pytest_symbol_selector(target)
            if selector["enabled"]:
                return [f"{pytest_command} -k {selector['symbol']}"], "targeted_symbol", selector
            return [pytest_command], "targeted", selector
        return ["pytest"], "fallback", _disabled_symbol_selector("unsafe_test_file")

    if target.framework == "unittest":
        unittest_command = _unittest_target_command(target.test_file)
        if unittest_command is not None:
            return [unittest_command], "targeted", _disabled_symbol_selector("framework_not_supported")

    return ["python -m unittest discover -s tests"], "fallback", _disabled_symbol_selector("framework_not_supported")


def _pytest_symbol_selector(target: TestGenerationTarget) -> dict:
    if target.all_symbols:
        return _disabled_symbol_selector("all_symbols_mode")

    if target.symbol is None or not target.symbol.name:
        return _disabled_symbol_selector("missing_symbol")

    if not SAFE_PYTEST_SYMBOL_PATTERN.fullmatch(target.symbol.name):
        return _disabled_symbol_selector("unsafe_symbol")

    return {
        "enabled": True,
        "symbol": target.symbol.name,
        "framework": "pytest",
    }


def _disabled_symbol_selector(reason: str) -> dict:
    return {
        "enabled": False,
        "reason": reason,
    }


def _pytest_target_command(test_file: str) -> str | None:
    try:
        validate_test_file_path(normalize_change_path(test_file))
    except WorkspaceError:
        return None

    normalized = normalize_change_path(test_file)
    path = PurePosixPath(normalized)

    if path.suffix != ".py" or ".." in path.parts or path.is_absolute():
        return None

    return f"pytest {path.as_posix()}"


def _unittest_target_command(test_file: str) -> str | None:
    try:
        validate_test_file_path(normalize_change_path(test_file))
    except WorkspaceError:
        return None

    normalized = normalize_change_path(test_file)
    path = PurePosixPath(normalized)

    if path.suffix != ".py" or ".." in path.parts or path.is_absolute():
        return None

    module_parts = list(path.with_suffix("").parts)

    if not module_parts or not all(part.isidentifier() for part in module_parts):
        return None

    return "python -m unittest " + ".".join(module_parts)


def _existing_tests_prompt_section(existing_tests_check: ExistingTestsCheck | None, force: bool) -> str:
    if existing_tests_check is None:
        return "- not available"

    lines = [
        f"- status: {existing_tests_check.status}",
        f"- force: {str(force).lower()}",
    ]

    for symbol, details in existing_tests_check.symbols.items():
        covered = "covered" if details.get("covered") else "missing"
        evidence = details.get("evidence")
        evidence_text = ", ".join(evidence) if isinstance(evidence, list) and evidence else "no evidence"
        lines.append(f"- {symbol}: {covered} ({evidence_text})")

    if force:
        lines.append("- Some or all symbols may already have tests. Add only complementary tests and avoid duplicates.")
    else:
        lines.append("- Generate tests only for requested missing symbols. Do not duplicate existing tests.")

    return "\n".join(lines)


def _existing_tests_summary_section(existing_tests_check: ExistingTestsCheck | None) -> str:
    if existing_tests_check is None:
        return "Not available."

    covered = "\n".join(f"- {symbol}" for symbol in existing_tests_check.symbols_covered) or "- none"
    missing = "\n".join(f"- {symbol}" for symbol in existing_tests_check.symbols_missing) or "- none"
    return f"""Status: {existing_tests_check.status}

Covered:
{covered}

Missing:
{missing}"""


def _structure_validation_summary_section(structure_validation: dict | None) -> str:
    if structure_validation is None:
        return "Not run."

    errors = "\n".join(f"- {error}" for error in structure_validation.get("errors", [])) or "- none"
    warnings = "\n".join(f"- {warning}" for warning in structure_validation.get("warnings", [])) or "- none"
    tests = "\n".join(f"- {test}" for test in structure_validation.get("discovered_tests", [])) or "- none"

    return f"""Status: {structure_validation.get("status", "unknown")}

Errors:
{errors}

Warnings:
{warnings}

Discovered tests:
{tests}"""


def _unittest_method_repair_summary_section(unittest_method_repair: dict | None) -> str:
    if unittest_method_repair is None:
        return "Not run."

    methods = "\n".join(f"- {method}" for method in unittest_method_repair.get("methods_repaired", [])) or "- none"
    lines = [
        f"Status: {unittest_method_repair.get('status', 'unknown')}",
    ]
    strategy = unittest_method_repair.get("strategy")
    if strategy:
        lines.append(f"Strategy: {strategy}")
    reason = unittest_method_repair.get("reason")
    if reason:
        lines.append(f"Reason: {reason}")
    lines.append("")
    lines.append("Methods:")
    lines.append(methods)

    return "\n".join(lines)


def _import_repair_summary_section(import_repair: dict | None) -> str:
    if import_repair is None:
        return "Not run."

    symbols = "\n".join(f"- {symbol}" for symbol in import_repair.get("symbols_added", [])) or "- none"
    reason = import_repair.get("reason")
    strategy = import_repair.get("strategy")
    lines = [
        f"Status: {import_repair.get('status', 'unknown')}",
    ]
    if strategy:
        lines.append(f"Strategy: {strategy}")
    if reason:
        lines.append(f"Reason: {reason}")
    lines.append("")
    lines.append("Symbols added:")
    lines.append(symbols)

    return "\n".join(lines)


def _structure_retry_summary_section(structure_retries: dict | None) -> str:
    if structure_retries is None:
        return "Not run."

    lines = [
        f"Max retries: {structure_retries.get('max', 0)}",
        f"Used: {structure_retries.get('used', 0)}",
        f"Result: {structure_retries.get('status', 'unknown')}",
    ]

    return "\n".join(lines)


def _generation_retry_summary_section(generation_retries: dict | None) -> str:
    if generation_retries is None:
        return "Not run."

    lines = [
        f"Max retries: {generation_retries.get('max', 0)}",
        f"Used: {generation_retries.get('used', 0)}",
        f"Result: {generation_retries.get('status', 'unknown')}",
    ]

    return "\n".join(lines)


def _sandbox_retry_summary_section(sandbox_retries: dict | None) -> str:
    if sandbox_retries is None:
        return "Not run."

    lines = [
        f"Max retries: {sandbox_retries.get('max', 0)}",
        f"Used: {sandbox_retries.get('used', 0)}",
        f"Result: {sandbox_retries.get('status', 'unknown')}",
    ]

    return "\n".join(lines)


def build_tests_inspect_payload(*, source_path: str, check: ExistingTestsCheck) -> dict:
    payload = check.to_dict()
    payload["source_path"] = source_path
    return payload


def build_tests_inspect_metadata(
    *,
    source_path: str,
    target: TestGenerationTarget,
    check: ExistingTestsCheck,
    status: str = "succeeded",
) -> dict:
    return {
        "mode": "advisory",
        "command": "tests inspect",
        "source_path": source_path,
        "test_file": target.test_file,
        "symbol": target.symbol.name if target.symbol is not None else None,
        "all": target.all_symbols,
        "status": status,
        "provider_called": False,
        "coverage_status": check.status,
    }


def render_tests_inspect_report(*, source_path: str, check: ExistingTestsCheck) -> str:
    covered_lines = []
    for symbol in check.symbols_covered:
        evidence = check.symbols[symbol].get("evidence", [])
        evidence_text = ", ".join(evidence) if evidence else "evidence unavailable"
        covered_lines.append(f"- {symbol}: {evidence_text}")

    missing_lines = [f"- {symbol}" for symbol in check.symbols_missing]
    covered = "\n".join(covered_lines) or "- none"
    missing = "\n".join(missing_lines) or "- none"
    symbols = _render_symbol_table(check)

    return f"""# Test Coverage Inspection

Source: {source_path}
Test file: {check.test_file}
Status: {check.status}
Mode: {check.mode}

## Symbols

{symbols}

## Covered

{covered}

## Missing

{missing}

## Next

trevvos tests add {source_path} {'--all' if check.mode == 'all_symbols' else '--symbol ' + check.symbols_requested[0]}
"""


def _render_symbol_table(check: ExistingTestsCheck) -> str:
    lines = []

    for symbol in check.symbols_requested:
        details = check.symbols[symbol]
        if details.get("covered"):
            evidence = details.get("evidence", [])
            evidence_text = ", ".join(evidence) if evidence else "covered"
            lines.append(f"- [covered] {symbol}: {evidence_text}")
        else:
            lines.append(f"- [missing] {symbol}")

    return "\n".join(lines) or "- none"


def raw_response_json(raw_response: str) -> dict:
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        return {"raw_response": raw_response}
    return parsed if isinstance(parsed, dict) else {"raw_response": raw_response}


def _python_module_name(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    without_suffix = path.with_suffix("")
    return ".".join(part for part in without_suffix.parts if part != "__init__")


def _ensure_inside_workspace(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError(f"Path must be inside workspace: {path}") from exc


def _relative_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
