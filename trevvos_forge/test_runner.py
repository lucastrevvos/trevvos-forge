import json
import os
import shutil
import shlex
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from trevvos_forge.exceptions import TestRunError


CONFIG_PATH = Path(".trevvos") / "config.json"
DEFAULT_SANDBOX_IGNORE_NAMES = {
    ".git",
    ".trevvos",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    ".DS_Store",
}


@dataclass(frozen=True)
class TestCommandResult:
    command: str
    exit_code: int | None
    duration_seconds: float
    status: str
    stdout: str
    stderr: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PatchApplyResult:
    patch_apply_check: str
    patch_apply: str
    stdout: str
    stderr: str

    @property
    def status(self) -> str:
        if self.patch_apply_check == "passed" and self.patch_apply == "passed":
            return "passed"

        return "failed"


@dataclass(frozen=True)
class TestRunResult:
    status: str
    commands: list[TestCommandResult]
    summary: dict[str, int]
    mode: str = "working_tree"
    sandbox: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "sandbox": _public_sandbox_metadata(self.sandbox),
            "status": self.status,
            "commands": [
                {
                    "command": command.command,
                    "exit_code": command.exit_code,
                    "duration_seconds": command.duration_seconds,
                    "status": command.status,
                }
                for command in self.commands
            ],
            "summary": self.summary,
        }


def load_test_commands(repo_root: Path) -> list[str]:
    config_file = repo_root / CONFIG_PATH

    if not config_file.exists():
        return detect_test_commands(repo_root)

    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TestRunError(f"Invalid JSON in {CONFIG_PATH}.") from exc

    if not isinstance(payload, dict):
        raise TestRunError(f"{CONFIG_PATH} must contain a JSON object.")

    commands = payload.get("test_commands")

    if not isinstance(commands, list):
        raise TestRunError(f"{CONFIG_PATH} must define test_commands as a list.")

    parsed_commands = []

    for index, command in enumerate(commands):
        if not isinstance(command, str) or not command.strip():
            raise TestRunError(f"Invalid test command at test_commands[{index}].")

        parsed_commands.append(command.strip())

    return parsed_commands


def detect_test_commands(repo_root: Path) -> list[str]:
    commands: list[str] = []

    if _looks_like_python_project(repo_root):
        if (repo_root / "tests").is_dir():
            commands.append("python -m unittest discover -s tests")

            compile_targets = [
                target
                for target in ["trevvos_forge", "tests"]
                if (repo_root / target).exists()
            ]

            if compile_targets:
                commands.append(f"python -m compileall {' '.join(compile_targets)}")

    package_json = repo_root / "package.json"

    if package_json.exists() and _package_has_test_script(package_json):
        commands.append("npm test")

    if _looks_like_dotnet_test_project(repo_root):
        commands.append("dotnet test")

    return commands


def run_test_commands(
    commands: list[str],
    repo_root: Path,
    timeout_seconds: int,
    mode: str = "working_tree",
    sandbox: dict[str, Any] | None = None,
) -> TestRunResult:
    if timeout_seconds <= 0:
        raise TestRunError("Timeout must be greater than zero seconds.")

    if not commands:
        return TestRunResult(
            status="not_configured",
            commands=[],
            summary={
                "total": 0,
                "passed": 0,
                "failed": 0,
                "timed_out": 0,
            },
            mode=mode,
            sandbox=sandbox,
        )

    command_results: list[TestCommandResult] = []

    for command in commands:
        result = _run_single_command(
            command=command,
            repo_root=repo_root,
            timeout_seconds=timeout_seconds,
        )
        command_results.append(result)

        if result.status != "passed":
            break

    return TestRunResult(
        status=_overall_status(command_results),
        commands=command_results,
        summary=_build_summary(command_results),
        mode=mode,
        sandbox=sandbox,
    )


def create_project_sandbox(
    repo_root: Path,
    ignore_names: set[str] | None = None,
) -> Path:
    resolved_root = repo_root.resolve()

    if not resolved_root.exists() or not resolved_root.is_dir():
        raise TestRunError(f"Workspace path is not a directory: {resolved_root}")

    sandbox_root = Path(tempfile.mkdtemp(prefix="trevvos-forge-sandbox-"))
    ignored_names = ignore_names or DEFAULT_SANDBOX_IGNORE_NAMES

    try:
        shutil.copytree(
            resolved_root,
            sandbox_root,
            dirs_exist_ok=True,
            ignore=_build_copy_ignore(ignored_names),
        )
    except Exception:
        shutil.rmtree(sandbox_root, ignore_errors=True)
        raise

    return sandbox_root


def apply_patch_in_sandbox(sandbox_root: Path, patch_path: Path) -> PatchApplyResult:
    resolved_patch = patch_path.resolve()

    if not resolved_patch.exists():
        raise TestRunError(f"Patch file not found: {patch_path}")

    check_result = _run_git_apply(
        sandbox_root=sandbox_root,
        patch_path=resolved_patch,
        check=True,
    )

    if check_result.returncode != 0:
        return PatchApplyResult(
            patch_apply_check="failed",
            patch_apply="not_run",
            stdout=check_result.stdout,
            stderr=check_result.stderr,
        )

    apply_result = _run_git_apply(
        sandbox_root=sandbox_root,
        patch_path=resolved_patch,
        check=False,
    )

    if apply_result.returncode != 0:
        return PatchApplyResult(
            patch_apply_check="passed",
            patch_apply="failed",
            stdout=check_result.stdout + apply_result.stdout,
            stderr=check_result.stderr + apply_result.stderr,
        )

    return PatchApplyResult(
        patch_apply_check="passed",
        patch_apply="passed",
        stdout=check_result.stdout + apply_result.stdout,
        stderr=check_result.stderr + apply_result.stderr,
    )


def run_tests_in_sandbox(
    *,
    repo_root: Path,
    patch_path: Path,
    commands: list[str],
    timeout_seconds: int,
    keep_sandbox: bool = False,
) -> TestRunResult:
    sandbox_root = create_project_sandbox(repo_root)
    sandbox_metadata: dict[str, Any] = {
        "enabled": True,
        "kept": keep_sandbox,
        "path": str(sandbox_root) if keep_sandbox else None,
        "runtime_path": str(sandbox_root),
        "patch_apply_check": "not_run",
        "patch_apply": "not_run",
    }

    try:
        patch_result = apply_patch_in_sandbox(
            sandbox_root=sandbox_root,
            patch_path=patch_path,
        )
        sandbox_metadata.update(
            {
                "patch_apply_check": patch_result.patch_apply_check,
                "patch_apply": patch_result.patch_apply,
                "patch_stdout": patch_result.stdout,
                "patch_stderr": patch_result.stderr,
            }
        )

        if patch_result.status != "passed":
            return TestRunResult(
                status="failed",
                commands=[],
                summary={
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "timed_out": 0,
                },
                mode="sandbox",
                sandbox=sandbox_metadata,
            )

        return run_test_commands(
            commands=commands,
            repo_root=sandbox_root,
            timeout_seconds=timeout_seconds,
            mode="sandbox",
            sandbox=sandbox_metadata,
        )
    finally:
        if not keep_sandbox:
            shutil.rmtree(sandbox_root, ignore_errors=True)


def write_test_artifacts(session_dir: Path, result: TestRunResult) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)

    (session_dir / "test_results.json").write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (session_dir / "test_output.log").write_text(
        _build_output_log(result),
        encoding="utf-8",
    )


def _run_single_command(
    *,
    command: str,
    repo_root: Path,
    timeout_seconds: int,
) -> TestCommandResult:
    started_at = time.monotonic()

    try:
        completed = subprocess.run(
            _split_command(command),
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except ValueError as exc:
        raise TestRunError(f"Invalid command syntax: {command}") from exc
    except FileNotFoundError as exc:
        raise TestRunError(f"Command executable not found: {command}") from exc
    except subprocess.TimeoutExpired as exc:
        return TestCommandResult(
            command=command,
            exit_code=None,
            duration_seconds=round(time.monotonic() - started_at, 3),
            status="timed_out",
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr),
        )

    status = "passed" if completed.returncode == 0 else "failed"

    return TestCommandResult(
        command=command,
        exit_code=completed.returncode,
        duration_seconds=round(time.monotonic() - started_at, 3),
        status=status,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _run_git_apply(
    *,
    sandbox_root: Path,
    patch_path: Path,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    command = ["git", "apply"]

    if check:
        command.append("--check")

    command.append(str(patch_path))

    return subprocess.run(
        command,
        cwd=sandbox_root,
        capture_output=True,
        text=True,
    )


def _looks_like_python_project(repo_root: Path) -> bool:
    return any(
        (repo_root / file_name).exists()
        for file_name in ["pyproject.toml", "setup.py", "setup.cfg"]
    )


def _package_has_test_script(package_json: Path) -> bool:
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False

    scripts = payload.get("scripts") if isinstance(payload, dict) else None

    return isinstance(scripts, dict) and isinstance(scripts.get("test"), str)


def _looks_like_dotnet_test_project(repo_root: Path) -> bool:
    if not any(repo_root.glob("*.sln")) and not any(repo_root.glob("*.csproj")):
        return False

    return any(
        "test" in project.name.lower()
        for project in repo_root.rglob("*.csproj")
    )


def _overall_status(command_results: list[TestCommandResult]) -> str:
    if not command_results:
        return "not_configured"

    for command in command_results:
        if command.status != "passed":
            return command.status

    return "passed"


def _build_summary(command_results: list[TestCommandResult]) -> dict[str, int]:
    return {
        "total": len(command_results),
        "passed": sum(1 for command in command_results if command.status == "passed"),
        "failed": sum(1 for command in command_results if command.status == "failed"),
        "timed_out": sum(1 for command in command_results if command.status == "timed_out"),
    }


def _build_output_log(result: TestRunResult) -> str:
    parts: list[str] = [
        f"Mode: {result.mode}",
    ]

    if result.mode == "sandbox":
        sandbox = result.sandbox or {}
        sandbox_path = sandbox.get("runtime_path") or sandbox.get("path") or "unavailable"
        parts.append(f"Sandbox: {sandbox_path}")
        parts.append(f"Patch apply check: {sandbox.get('patch_apply_check', 'not_run')}")
        parts.append(f"Patch apply: {sandbox.get('patch_apply', 'not_run')}")

        patch_stdout = sandbox.get("patch_stdout")
        patch_stderr = sandbox.get("patch_stderr")

        if isinstance(patch_stdout, str) and patch_stdout.strip():
            parts.append(patch_stdout.rstrip("\n"))

        if isinstance(patch_stderr, str) and patch_stderr.strip():
            parts.append(patch_stderr.rstrip("\n"))
    else:
        parts.append("Sandbox: disabled")

    parts.append("")

    for command in result.commands:
        parts.append(f"$ {command.command}")

        if command.stdout:
            parts.append(command.stdout.rstrip("\n"))

        if command.stderr:
            parts.append(command.stderr.rstrip("\n"))

        exit_code = "timeout" if command.exit_code is None else str(command.exit_code)
        parts.append(f"Exit code: {exit_code}")
        parts.append(f"Duration: {command.duration_seconds:.3f}s")
        parts.append("")

    if not result.commands:
        parts.append("No test commands configured or detected.")

    return "\n".join(parts).rstrip("\n") + "\n"


def _coerce_output(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, bytes):
        return value.decode(errors="replace")

    return str(value)


def _split_command(command: str) -> list[str]:
    parts = shlex.split(command, posix=os.name != "nt")

    if os.name == "nt":
        parts = [_strip_outer_quotes(part) for part in parts]

    return parts


def _strip_outer_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]

    return value


def _build_copy_ignore(ignore_names: set[str]):
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in ignore_names}

    return ignore


def _public_sandbox_metadata(sandbox: dict[str, Any] | None) -> dict:
    if sandbox is None:
        return {
            "enabled": False,
        }

    return {
        key: value
        for key, value in sandbox.items()
        if key not in {"runtime_path", "patch_stdout", "patch_stderr"}
    }
