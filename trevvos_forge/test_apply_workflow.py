import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trevvos_forge.exceptions import DiffError, FileChangeOutputError, WorkspaceError
from trevvos_forge.file_change_outputs import parse_file_changes_output
from trevvos_forge.sessions import (
    ForgeSession,
    get_current_session,
    get_session,
    list_sessions,
    update_session_status,
    write_session_json,
)
from trevvos_forge.test_generation import validate_file_changes_are_tests_only


TESTS_ADD_COMMAND = "tests add"


@dataclass(frozen=True)
class TestApplyRequest:
    repo_root: Path
    session_id: str | None


@dataclass(frozen=True)
class TestApplyResult:
    status: str  # "applied", "blocked", "already_applied"
    session_id: str
    session_path: Path
    files_changed: list[str]
    applied: bool
    message: str
    exit_code: int
    block_reason: str | None = None
    apply_result: dict | None = None
    suggestion: str | None = None
    already_applied: bool = False
    reason: str | None = None


def run_tests_apply_workflow(request: TestApplyRequest) -> TestApplyResult:
    workspace_root = request.repo_root.resolve()

    if request.session_id:
        session = get_session(root=workspace_root, session_id=request.session_id)
        return _run_apply_for_session(workspace_root=workspace_root, session=session)

    session = get_current_session(workspace_root)
    result = _run_apply_for_session(workspace_root=workspace_root, session=session)

    if result.status == "blocked":
        suggestion = _suggest_latest_validated_session(workspace_root, exclude_id=result.session_id)
        return TestApplyResult(
            status=result.status,
            session_id=result.session_id,
            session_path=result.session_path,
            files_changed=result.files_changed,
            applied=result.applied,
            message=result.message,
            exit_code=result.exit_code,
            block_reason=result.block_reason,
            apply_result=result.apply_result,
            suggestion=suggestion,
            already_applied=result.already_applied,
            reason=result.reason,
        )

    return result


def _run_apply_for_session(*, workspace_root: Path, session: ForgeSession) -> TestApplyResult:
    session_id = session.metadata.id
    session_path = session.path

    if session.metadata.command != TESTS_ADD_COMMAND:
        return _blocked(
            session_id,
            session_path,
            "not_tests_add",
            f"Session {session_id} is not a tests add session (command: {session.metadata.command}).",
        )

    patch_path = session_path / "test_diff.patch"
    if not patch_path.exists():
        return _blocked(session_id, session_path, "no_patch", "No validated test patch found.")

    sandbox_results_path = session_path / "test_sandbox_results.json"
    if not sandbox_results_path.exists():
        return _blocked(session_id, session_path, "no_sandbox_results", "No sandbox results found.")
    sandbox_status = _read_json_field(sandbox_results_path, "status")
    if sandbox_status != "passed":
        return _blocked(
            session_id,
            session_path,
            "sandbox_not_passed",
            f"Sandbox tests did not pass (status: {sandbox_status}).",
        )

    metadata_path = session_path / "test_generation_metadata.json"
    if not metadata_path.exists():
        return _blocked(session_id, session_path, "no_metadata", "No test generation metadata found.")
    write_allowed = _read_json_field(metadata_path, "write_allowed")
    if not write_allowed:
        return _blocked(
            session_id,
            session_path,
            "write_not_allowed",
            "Session write was not allowed (sandbox tests may have failed).",
        )

    structure_path = session_path / "test_structure_validation.json"
    if not structure_path.exists():
        return _blocked(
            session_id, session_path, "no_structure_validation", "No test structure validation found."
        )
    structure_status = _read_json_field(structure_path, "status")
    if structure_status != "passed":
        return _blocked(
            session_id,
            session_path,
            "structure_not_passed",
            f"Test structure validation did not pass (status: {structure_status}).",
        )

    file_changes_path = session_path / "test_file_changes.json"
    if not file_changes_path.exists():
        return _blocked(session_id, session_path, "no_file_changes", "No file changes found.")
    try:
        file_changes = parse_file_changes_output(file_changes_path.read_text(encoding="utf-8"))
        validate_file_changes_are_tests_only(file_changes)
    except (FileChangeOutputError, WorkspaceError, DiffError) as exc:
        return _blocked(session_id, session_path, "guardrail_failed", f"Guardrail check failed: {exc}")

    files_changed = [change.path for change in file_changes.changes]

    check_proc = _run_git(["git", "apply", "--check", str(patch_path)], cwd=workspace_root)
    if check_proc.returncode != 0:
        # Try reverse check to distinguish "already applied" from "truly obsolete"
        reverse_proc = _run_git(
            ["git", "apply", "--reverse", "--check", str(patch_path)], cwd=workspace_root
        )
        if reverse_proc.returncode == 0:
            already_result: dict[str, Any] = {
                "applied": False,
                "already_applied": True,
                "session": session_id,
                "patch_path": str(patch_path),
                "reason": "reverse_check_passed",
                "files_changed": files_changed,
                "stdout": reverse_proc.stdout.strip(),
                "stderr": reverse_proc.stderr.strip(),
            }
            write_session_json(session, "test_apply_result.json", already_result)
            update_session_status(session, "tests_already_applied")
            return TestApplyResult(
                status="already_applied",
                session_id=session_id,
                session_path=session_path,
                files_changed=files_changed,
                applied=False,
                already_applied=True,
                reason="reverse_check_passed",
                apply_result=already_result,
                message="[yellow]Test patch already appears to be applied.[/yellow]",
                exit_code=0,
            )

        err = check_proc.stderr.strip() or check_proc.stdout.strip() or "unknown error"
        failed_apply: dict[str, Any] = {
            "applied": False,
            "already_applied": False,
            "session": session_id,
            "patch_path": str(patch_path),
            "reason": "check_failed",
            "reverse_check": "failed",
            "files_changed": files_changed,
            "error": "git apply --check failed",
            "stdout": check_proc.stdout.strip(),
            "stderr": check_proc.stderr.strip(),
        }
        write_session_json(session, "test_apply_result.json", failed_apply)
        return _blocked(
            session_id,
            session_path,
            "check_failed",
            (
                "Validated test patch is no longer applicable to the current working tree.\n"
                "The working tree may have changed since the test patch was generated.\n"
                "Run: trevvos tests add <source_path> --symbol <name>"
            ),
            apply_result=failed_apply,
        )

    apply_proc = _run_git(["git", "apply", str(patch_path)], cwd=workspace_root)
    if apply_proc.returncode != 0:
        err = apply_proc.stderr.strip() or apply_proc.stdout.strip() or "unknown error"
        raise WorkspaceError(f"Patch apply failed. Git error: {err}")

    apply_result: dict[str, Any] = {
        "applied": True,
        "already_applied": False,
        "session": session_id,
        "patch_path": str(patch_path),
        "reason": "applied",
        "files_changed": files_changed,
        "stdout": apply_proc.stdout.strip(),
        "stderr": apply_proc.stderr.strip(),
    }
    write_session_json(session, "test_apply_result.json", apply_result)
    update_session_status(session, "tests_applied")

    return TestApplyResult(
        status="applied",
        session_id=session_id,
        session_path=session_path,
        files_changed=files_changed,
        applied=True,
        already_applied=False,
        reason="applied",
        apply_result=apply_result,
        message="[green]Test patch applied successfully.[/green]",
        exit_code=0,
    )


def render_tests_apply_result(*, result: TestApplyResult, console: Any) -> None:
    console.print(result.message)
    if result.status == "applied":
        console.print(f"Session: {result.session_id}")
        console.print("\n[bold]Files changed[/bold]")
        for file_path in result.files_changed:
            console.print(f"  - {file_path}")
        console.print("\n[bold]Saved files[/bold]")
        console.print(f"  - {result.session_path / 'test_apply_result.json'}")
    elif result.status == "already_applied":
        console.print(f"Session: {result.session_id}")
        console.print("Nothing to do.")
        console.print(f"  - {result.session_path / 'test_apply_result.json'}")
    elif result.status == "blocked":
        if result.block_reason:
            console.print(f"Reason: {result.block_reason}")
        if isinstance(result.apply_result, dict) and not result.apply_result.get("applied"):
            console.print(f"Review {result.session_path / 'test_apply_result.json'}.")
    if result.suggestion:
        console.print(f"\n{result.suggestion}")


def find_latest_validated_tests_add_session(workspace_root: Path) -> ForgeSession | None:
    for session in list_sessions(workspace_root):
        if session.metadata.command != TESTS_ADD_COMMAND:
            continue
        if _is_session_validated(session):
            return session
    return None


def find_best_tests_apply_session(
    workspace_root: Path,
) -> tuple[ForgeSession | None, str]:
    """Return (session, reason) where reason is 'applicable', 'already_applied', or 'none'.

    Iterates validated tests add sessions from newest to oldest, running
    git apply --check and --reverse --check to find the best candidate.
    """
    candidates: list[ForgeSession] = []
    for session in list_sessions(workspace_root):
        if session.metadata.command != TESTS_ADD_COMMAND:
            continue
        if _is_session_validated(session):
            candidates.append(session)

    for session in candidates:
        patch_path = session.path / "test_diff.patch"
        check = _run_git(["git", "apply", "--check", str(patch_path)], cwd=workspace_root)
        if check.returncode == 0:
            return session, "applicable"
        reverse = _run_git(
            ["git", "apply", "--reverse", "--check", str(patch_path)], cwd=workspace_root
        )
        if reverse.returncode == 0:
            return session, "already_applied"

    return None, "none"


def _suggest_latest_validated_session(workspace_root: Path, *, exclude_id: str) -> str:
    sessions = list_sessions(workspace_root)
    for session in sessions:
        if session.metadata.id == exclude_id:
            continue
        if session.metadata.command != TESTS_ADD_COMMAND:
            continue
        if not _is_session_validated(session):
            continue
        return (
            f"Latest validated tests add session:\n"
            f"  {session.metadata.id}\n\n"
            f"Apply it with:\n"
            f"  trevvos tests apply --session {session.metadata.id} --yes"
        )
    return "No validated tests add sessions found.\nRun `trevvos tests add <source_path> --symbol <name>` first."


def _is_session_validated(session: ForgeSession) -> bool:
    if not (session.path / "test_diff.patch").exists():
        return False
    sandbox_status = _read_json_field(session.path / "test_sandbox_results.json", "status")
    if sandbox_status != "passed":
        return False
    write_allowed = _read_json_field(session.path / "test_generation_metadata.json", "write_allowed")
    if not write_allowed:
        return False
    structure_status = _read_json_field(session.path / "test_structure_validation.json", "status")
    if structure_status != "passed":
        return False
    return True


def _blocked(
    session_id: str,
    session_path: Path,
    block_reason: str,
    message: str,
    apply_result: dict | None = None,
) -> TestApplyResult:
    return TestApplyResult(
        status="blocked",
        session_id=session_id,
        session_path=session_path,
        files_changed=[],
        applied=False,
        block_reason=block_reason,
        apply_result=apply_result,
        message=f"[red]{message}[/red]",
        exit_code=1,
    )


def _read_json_field(path: Path, field: str) -> Any:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data.get(field) if isinstance(data, dict) else None


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="git not found")
