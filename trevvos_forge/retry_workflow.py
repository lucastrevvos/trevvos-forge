import json
from pathlib import Path, PurePosixPath
from typing import Any

from trevvos_forge.exceptions import DiffError, SessionError
from trevvos_forge.prompt_catalog import get_prompt
from trevvos_forge.sessions import ForgeSession, read_session_text, write_session_json


SMALL_FILE_LINE_LIMIT = 120


def build_retry_context(session: ForgeSession, repo_root: Path) -> dict:
    operation_error = _read_json_file(session.path / "operation_error.json")
    file_changes_error = _read_json_file(session.path / "file_changes_error.json")

    if operation_error is None and file_changes_error is None:
        raise DiffError(
            "No retryable diff error found for current session. Expected operation_error.json or file_changes_error.json."
        )

    previous_error = operation_error if isinstance(operation_error, dict) else file_changes_error
    if not isinstance(previous_error, dict):
        previous_error = {}

    error_path = previous_error.get("path")
    current_file = _current_file_context(repo_root=repo_root, error_path=error_path)

    return {
        "retry_error_source": "operation_error" if isinstance(operation_error, dict) else "file_changes_error",
        "user_request": _read_optional_session_text(session, "user_request.txt"),
        "plan_markdown": _read_optional_session_text(session, "plan.md"),
        "plan_json": _read_json_file(session.path / "plan.json"),
        "selected_files": _read_json_file(session.path / "selected_files.json"),
        "workspace_context": _read_optional_session_text(session, "context.md"),
        "operation_error": operation_error,
        "file_changes_error": file_changes_error,
        "previous_error": previous_error,
        "raw_file_changes_response": _read_optional_session_text(session, "file_changes_raw_response.json"),
        "current_file": current_file,
    }


def build_retry_prompt(context: dict) -> str:
    prompt_template = get_prompt("file_changes_retry")

    return prompt_template.render(
        retry_context=render_retry_context(context),
    )


def render_retry_context(context: dict) -> str:
    previous_error = context.get("previous_error")
    file_changes_error = context.get("file_changes_error")
    current_file = context.get("current_file")

    if not isinstance(previous_error, dict):
        previous_error = {}

    if not isinstance(file_changes_error, dict):
        file_changes_error = {}

    if not isinstance(current_file, dict):
        current_file = {}

    lines = [
        "Original user request:",
        str(context.get("user_request") or ""),
        "",
        "Plan markdown:",
        str(context.get("plan_markdown") or ""),
        "",
        "Plan JSON:",
        _json_block(context.get("plan_json")),
        "",
        "Selected files:",
        _json_block(context.get("selected_files")),
        "",
        "Retry error source:",
        str(context.get("retry_error_source") or "unknown"),
        "",
        "Previous error:",
        _json_block(previous_error),
        "",
        f"Error type: {previous_error.get('error_type') or 'unknown'}",
        f"Path: {previous_error.get('path') or 'unknown'}",
        f"Operation: {previous_error.get('operation') or 'unknown'}",
        f"Target: {previous_error.get('target') or 'unknown'}",
        f"Suggested resolution: {previous_error.get('suggested_resolution') or 'unknown'}",
        "",
        "Previous raw file_changes response:",
        str(context.get("raw_file_changes_response") or "(unavailable)"),
        "",
        f"Current file: {current_file.get('path') or 'unavailable'}",
        f"Total lines: {current_file.get('total_lines') if current_file.get('total_lines') is not None else 'unknown'}",
        f"Small file: {str(bool(current_file.get('small_file'))).lower()}",
        "",
        "Markdown headings:",
        "\n".join(str(heading) for heading in current_file.get("markdown_headings", [])) or "(none)",
        "",
        "Content with line numbers:",
        str(current_file.get("content_with_line_numbers") or "(unavailable)"),
        "",
        "Raw workspace context from the previous attempt:",
        str(context.get("workspace_context") or ""),
    ]

    return "\n".join(lines).strip()


def build_retry_metadata(
    *,
    session: ForgeSession,
    prompt_ref: str,
    status: str,
    operation_error: dict[str, Any],
) -> dict:
    retry_count = _next_retry_count(session.path)

    return {
        "retry": True,
        "retry_count": retry_count,
        "previous_error_source": _previous_error_source(operation_error),
        "previous_error_type": operation_error.get("error_type"),
        "previous_operation": operation_error.get("operation"),
        "previous_target": operation_error.get("target"),
        "prompt": prompt_ref,
        "status": status,
    }


def write_retry_metadata(session: ForgeSession, metadata: dict) -> None:
    write_session_json(session, "retry_metadata.json", metadata)


def _current_file_context(*, repo_root: Path, error_path: Any) -> dict:
    if not isinstance(error_path, str) or not error_path.strip():
        return _missing_file_context(None)

    relative_path = _normalize_relative_path(error_path)
    target_path = (repo_root / relative_path).resolve()

    try:
        target_path.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise DiffError(f"Refusing to read retry context outside workspace: {relative_path}") from exc

    if not target_path.exists() or not target_path.is_file():
        return _missing_file_context(relative_path)

    try:
        content = target_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DiffError(f"Cannot read retry context for non-UTF-8 file: {relative_path}") from exc
    except PermissionError as exc:
        raise DiffError(f"Permission denied while reading retry context: {relative_path}") from exc

    normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized_content.splitlines()

    return {
        "path": relative_path,
        "exists": True,
        "content": normalized_content,
        "content_with_line_numbers": _numbered_content(normalized_content),
        "total_lines": len(lines),
        "small_file": len(lines) < SMALL_FILE_LINE_LIMIT,
        "markdown_headings": _markdown_headings(lines) if relative_path.lower().endswith(".md") else [],
    }


def _missing_file_context(relative_path: str | None) -> dict:
    return {
        "path": relative_path,
        "exists": False,
        "content": "",
        "content_with_line_numbers": "",
        "total_lines": None,
        "small_file": False,
        "markdown_headings": [],
    }


def _numbered_content(content: str) -> str:
    lines = content.splitlines()

    if not lines:
        return ""

    return "\n".join(f"{index} | {line}" for index, line in enumerate(lines, start=1))


def _markdown_headings(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.lstrip().startswith("#")]


def _normalize_relative_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/")

    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]

    pure_path = PurePosixPath(normalized)

    if pure_path.is_absolute() or normalized.startswith("/") or _has_windows_drive(normalized):
        raise DiffError(f"Refusing to read retry context for absolute path: {normalized}")

    if ".." in pure_path.parts:
        raise DiffError(f"Refusing to read retry context for path traversal: {normalized}")

    return str(pure_path)


def _has_windows_drive(path: str) -> bool:
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()


def _read_optional_session_text(session: ForgeSession, file_name: str) -> str:
    try:
        return read_session_text(session, file_name)
    except SessionError:
        return ""


def _previous_error_source(error: dict[str, Any]) -> str:
    if "raw_response_path" in error:
        return "file_changes_error"

    return "operation_error"


def _read_json_file(path: Path) -> Any:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DiffError(f"Session JSON is invalid: {path.name}") from exc


def _json_block(value: Any) -> str:
    if value is None:
        return "null"

    return json.dumps(value, indent=2, ensure_ascii=False)


def _next_retry_count(session_path: Path) -> int:
    metadata = _read_json_file(session_path / "retry_metadata.json")

    if not isinstance(metadata, dict):
        return 1

    retry_count = metadata.get("retry_count")

    if not isinstance(retry_count, int) or retry_count < 0:
        return 1

    return retry_count + 1
