import ast
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from trevvos_forge.exceptions import DiffError, WorkspaceError
from trevvos_forge.file_change_outputs import FileChangesOutput


TEST_FILE_ERROR = "Test file must be inside a tests directory or match test_*.py / *_test.py."


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
) -> str:
    existing_test = test_content if test_content is not None else "(test file does not exist yet)"
    mode = "all_symbols" if target.all_symbols else "single_symbol"
    requested_symbol = target.symbol.name if target.symbol is not None else "(all)"
    symbol_kind = target.symbol.kind if target.symbol is not None else "(multiple)"
    symbol_line = str(target.symbol.line) if target.symbol is not None else "(multiple)"
    symbols_to_test = "\n".join(f"- {symbol.name}" for symbol in target.symbols)
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
```"""


def build_test_generation_summary(
    *,
    target: TestGenerationTarget,
    files_changed: list[str],
    write: bool,
    status: str,
) -> str:
    changed = "\n".join(f"- {path}" for path in files_changed) or "- none"
    symbol = target.symbol.name if target.symbol is not None else "all"
    symbols_targeted = "\n".join(f"- {symbol.name}" for symbol in target.symbols)
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
) -> dict:
    return {
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
