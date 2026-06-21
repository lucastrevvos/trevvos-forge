import json
import os
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from trevvos_forge.exceptions import TestRunError


CONFIG_PATH = Path(".trevvos") / "config.json"


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
class TestRunResult:
    status: str
    commands: list[TestCommandResult]
    summary: dict[str, int]

    def to_dict(self) -> dict:
        return {
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
    )


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
    parts: list[str] = []

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

    if not parts:
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
