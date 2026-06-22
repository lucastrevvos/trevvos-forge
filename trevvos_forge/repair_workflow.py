import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from trevvos_forge.exceptions import DiffError, RepairNotRepairableError, SessionError
from trevvos_forge.prompt_catalog import get_prompt
from trevvos_forge.sessions import ForgeSession, read_session_text, write_session_json


SMALL_FILE_LINE_LIMIT = 120
PATCH_PREVIEW_LINE_LIMIT = 220
LOG_TAIL_LINE_LIMIT = 120
NO_VALID_DIFF_REPAIR_MESSAGE = (
    "No valid diff found to repair.\n"
    "If diff generation failed, run `trevvos diff --retry` instead."
)


def build_repair_context(session: ForgeSession, repo_root: Path, source: str | None = None) -> dict:
    plan_json = _read_json_file(session.path / "plan.json")
    file_changes = _read_json_file(session.path / "file_changes.json")
    _validate_repairable_diff(session.path, file_changes)
    semantic_review = _read_json_file(session.path / "semantic_review.json")
    llm_review = _read_json_file(session.path / "llm_review.json")
    cli_regression_check = _read_json_file(session.path / "cli_regression_check.json")
    operation_error = _read_json_file(session.path / "operation_error.json")
    sandbox_test_results = _read_json_file(session.path / "sandbox_test_results.json")
    working_tree_test_results = _read_json_file(session.path / "working_tree_test_results.json")
    legacy_test_results = _read_json_file(session.path / "test_results.json")

    if not isinstance(sandbox_test_results, dict) and _test_mode(legacy_test_results) == "sandbox":
        sandbox_test_results = legacy_test_results

    if not isinstance(working_tree_test_results, dict) and _test_mode(legacy_test_results) == "working_tree":
        working_tree_test_results = legacy_test_results

    sandbox_log = _read_optional_file_text(session.path / "sandbox_test_output.log")
    working_tree_log = _read_optional_file_text(session.path / "working_tree_test_output.log")

    if sandbox_log is None and _test_mode(legacy_test_results) == "sandbox":
        sandbox_log = _read_optional_file_text(session.path / "test_output.log")

    if working_tree_log is None and _test_mode(legacy_test_results) == "working_tree":
        working_tree_log = _read_optional_file_text(session.path / "test_output.log")

    reason = _detect_repair_reason(
        source=source,
        sandbox_test_results=sandbox_test_results,
        working_tree_test_results=working_tree_test_results,
        semantic_review=semantic_review,
        llm_review=llm_review,
        cli_regression_check=cli_regression_check,
    )

    if reason is None:
        raise DiffError("No repairable failure found for current session.")

    patch_text = _read_optional_file_text(session.path / "diff.patch") or ""
    diff_warnings = _read_json_file(session.path / "diff_warnings.json")
    plan_constraints_check = _read_json_file(session.path / "plan_constraints_check.json")

    relevant_paths = _relevant_paths(
        repo_root=repo_root,
        file_changes=file_changes,
        plan_json=plan_json,
        operation_error=operation_error,
        logs=[sandbox_log or "", working_tree_log or ""],
    )

    evidence_used = _evidence_used(
        session.path,
        sandbox_test_results=sandbox_test_results,
        working_tree_test_results=working_tree_test_results,
        llm_review=llm_review,
    )

    return {
        "reason": reason,
        "user_request": _read_optional_session_text(session, "user_request.txt"),
        "plan": _plan_fields(plan_json),
        "plan_markdown": _read_optional_session_text(session, "plan.md"),
        "file_changes": file_changes,
        "patch_preview": _limit_lines(patch_text, PATCH_PREVIEW_LINE_LIMIT),
        "sandbox_test_results": sandbox_test_results,
        "sandbox_test_output_tail": _tail_lines(sandbox_log or "", LOG_TAIL_LINE_LIMIT),
        "working_tree_test_results": working_tree_test_results,
        "working_tree_test_output_tail": _tail_lines(working_tree_log or "", LOG_TAIL_LINE_LIMIT),
        "semantic_review": semantic_review,
        "llm_review": llm_review,
        "cli_regression_check": cli_regression_check,
        "operation_error": operation_error,
        "plan_constraints_check": plan_constraints_check,
        "warnings": _warnings(diff_warnings, semantic_review, llm_review, cli_regression_check),
        "current_files": [
            _current_file_context(repo_root=repo_root, relative_path=path)
            for path in relevant_paths
        ],
        "evidence_used": evidence_used,
    }


def build_repair_prompt(context: dict) -> str:
    prompt_template = get_prompt("repair_file_changes")

    return prompt_template.render(
        repair_context=render_repair_context(context),
    )


def render_repair_context(context: dict) -> str:
    return "\n".join(
        [
            "Repair reason:",
            str(context.get("reason") or "unknown"),
            "",
            "Original user request:",
            str(context.get("user_request") or ""),
            "",
            "Plan fields:",
            _json_block(context.get("plan")),
            "",
            "Plan markdown:",
            str(context.get("plan_markdown") or ""),
            "",
            "Current file_changes.json:",
            _json_block(context.get("file_changes")),
            "",
            "Current patch preview:",
            str(context.get("patch_preview") or ""),
            "",
            "Sandbox test results:",
            _json_block(context.get("sandbox_test_results")),
            "",
            "Sandbox test output tail:",
            str(context.get("sandbox_test_output_tail") or ""),
            "",
            "Working tree test results:",
            _json_block(context.get("working_tree_test_results")),
            "",
            "Working tree test output tail:",
            str(context.get("working_tree_test_output_tail") or ""),
            "",
            "Semantic review:",
            _json_block(context.get("semantic_review")),
            "",
            "LLM review:",
            _json_block(context.get("llm_review")),
            "",
            "CLI regression check:",
            _json_block(context.get("cli_regression_check")),
            "",
            "CLI regression summary:",
            _cli_regression_summary(context.get("cli_regression_check")),
            "",
            "Operation error:",
            _json_block(context.get("operation_error")),
            "",
            "Plan constraints check:",
            _json_block(context.get("plan_constraints_check")),
            "",
            "Warnings:",
            _json_block(context.get("warnings")),
            "",
            "Current relevant files:",
            _json_block(context.get("current_files")),
            "",
            "Current workspace file content:",
            _current_workspace_content_section(context.get("current_files")),
        ]
    ).strip()


def build_repair_metadata(
    *,
    session: ForgeSession,
    prompt_ref: str,
    status: str,
    reason: str,
    evidence_used: list[str],
    error: str | None = None,
) -> dict:
    metadata = {
        "repair": True,
        "repair_count": _next_repair_count(session.path),
        "reason": reason,
        "status": status,
        "prompt": prompt_ref,
        "evidence_used": evidence_used,
    }

    if error:
        metadata["error"] = error

    return metadata


def write_repair_metadata(session: ForgeSession, metadata: dict) -> None:
    write_session_json(session, "repair_metadata.json", metadata)


def build_not_repairable_metadata(session: ForgeSession) -> dict:
    return {
        "repair": True,
        "repair_count": _next_repair_count(session.path),
        "status": "not_repairable",
        "reason": "missing_valid_diff",
        "suggested_next_command": "trevvos diff --retry",
    }


def _validate_repairable_diff(session_path: Path, file_changes: Any) -> None:
    patch_path = session_path / "diff.patch"

    if not patch_path.exists() or not patch_path.read_text(encoding="utf-8").strip():
        raise RepairNotRepairableError(NO_VALID_DIFF_REPAIR_MESSAGE)

    if not isinstance(file_changes, dict) or not isinstance(file_changes.get("changes"), list):
        raise RepairNotRepairableError(NO_VALID_DIFF_REPAIR_MESSAGE)

    if not file_changes["changes"]:
        raise RepairNotRepairableError(NO_VALID_DIFF_REPAIR_MESSAGE)


def _detect_repair_reason(
    *,
    source: str | None,
    sandbox_test_results: Any,
    working_tree_test_results: Any,
    semantic_review: Any,
    llm_review: Any,
    cli_regression_check: Any,
) -> str | None:
    source_map = {
        "sandbox": "sandbox_failed",
        "working-tree": "working_tree_failed",
        "review": "review_concerns",
    }
    if source in source_map:
        return source_map[source]

    if _test_status(sandbox_test_results) in {"failed", "timed_out"}:
        return "sandbox_failed"

    if _test_status(working_tree_test_results) in {"failed", "timed_out"}:
        return "working_tree_failed"

    if isinstance(cli_regression_check, dict) and cli_regression_check.get("status") == "failed":
        return "cli_regression_failed"

    if _has_concerns(semantic_review):
        return "semantic_review_concerns"

    if _has_concerns(llm_review):
        return "llm_review_concerns"

    plan_review = semantic_review.get("plan_review") if isinstance(semantic_review, dict) else None
    if isinstance(plan_review, dict) and plan_review.get("plan_commands_executed") in {"no", "partial"}:
        return "missing_plan_command_evidence"

    return None


def _has_concerns(review: Any) -> bool:
    if not isinstance(review, dict):
        return False

    if review.get("verdict") in {"has_concerns", "blocked"}:
        return True

    concerns = review.get("concerns")
    return isinstance(concerns, list) and any(isinstance(item, str) and item.strip() for item in concerns)


def _test_status(test_results: Any) -> str:
    if not isinstance(test_results, dict):
        return "not_run"

    status = test_results.get("status")
    return status if isinstance(status, str) else "unknown"


def _test_mode(test_results: Any) -> str | None:
    if not isinstance(test_results, dict):
        return None

    mode = test_results.get("mode", "working_tree")
    return mode if isinstance(mode, str) else None


def _plan_fields(plan_json: Any) -> dict[str, list[str]]:
    if not isinstance(plan_json, dict):
        plan_json = {}

    return {
        "expected_behavior": _string_list(plan_json.get("expected_behavior")),
        "acceptance_criteria": _string_list(plan_json.get("acceptance_criteria")),
        "suggested_verification_commands": _string_list(plan_json.get("suggested_verification_commands")),
        "files_to_create": _string_list(plan_json.get("files_to_create")),
        "files_to_modify": _string_list(plan_json.get("files_to_modify")),
        "files_not_to_modify": _string_list(plan_json.get("files_not_to_modify")),
    }


def _relevant_paths(
    *,
    repo_root: Path,
    file_changes: Any,
    plan_json: Any,
    operation_error: Any,
    logs: list[str],
) -> list[str]:
    paths: list[str] = []

    if isinstance(file_changes, dict) and isinstance(file_changes.get("changes"), list):
        for change in file_changes["changes"]:
            if isinstance(change, dict) and isinstance(change.get("path"), str):
                paths.append(change["path"])

    if isinstance(plan_json, dict):
        for key in ["files_to_modify", "files_to_create"]:
            paths.extend(_string_list(plan_json.get(key)))

    if isinstance(operation_error, dict) and isinstance(operation_error.get("path"), str):
        paths.append(operation_error["path"])

    for log in logs:
        paths.extend(_paths_from_log(log))

    deduped: list[str] = []
    seen: set[str] = set()

    for path in paths:
        try:
            normalized = _normalize_relative_path(path)
        except DiffError:
            continue

        candidate = repo_root / normalized
        if normalized not in seen and (candidate.exists() or normalized in paths):
            deduped.append(normalized)
            seen.add(normalized)

    return deduped


def _current_workspace_content_section(current_files: Any) -> str:
    if not isinstance(current_files, list) or not current_files:
        return "(none)"

    sections: list[str] = []
    for file_context in current_files:
        if not isinstance(file_context, dict):
            continue
        path = file_context.get("path") or "unknown"
        sections.append(f"Current workspace content for {path}:")
        if file_context.get("exists"):
            sections.append(str(file_context.get("content_with_line_numbers") or ""))
        else:
            sections.append("<file does not exist>")
        sections.append("")

    return "\n".join(sections).strip() or "(none)"


def _paths_from_log(log: str) -> list[str]:
    matches = re.findall(r"[\w./\\-]+\.(?:py|md|txt|json|toml|yaml|yml|js|ts|tsx|jsx)", log)
    return [match for match in matches if not match.startswith(".trevvos")]


def _current_file_context(*, repo_root: Path, relative_path: str) -> dict:
    normalized = _normalize_relative_path(relative_path)
    target_path = (repo_root / normalized).resolve()

    try:
        target_path.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise DiffError(f"Refusing to read repair context outside workspace: {normalized}") from exc

    if not target_path.exists() or not target_path.is_file():
        return {
            "path": normalized,
            "exists": False,
            "content_with_line_numbers": "",
            "total_lines": None,
            "small_file": False,
        }

    try:
        content = target_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DiffError(f"Cannot read repair context for non-UTF-8 file: {normalized}") from exc

    normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized_content.splitlines()

    return {
        "path": normalized,
        "exists": True,
        "content_with_line_numbers": _numbered_content(normalized_content),
        "total_lines": len(lines),
        "small_file": len(lines) < SMALL_FILE_LINE_LIMIT,
    }


def _warnings(*values: Any) -> list[str]:
    warnings: list[str] = []

    for value in values:
        if not isinstance(value, dict):
            continue

        warnings.extend(_string_list(value.get("warnings")))

    return _dedupe_strings(warnings)


def _cli_regression_summary(cli_regression_check: Any) -> str:
    if not isinstance(cli_regression_check, dict) or cli_regression_check.get("status") != "failed":
        return "(none)"

    lines = ["CLI regression detected:"]
    checks = cli_regression_check.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            path = check.get("path", "unknown")
            removed = _dedupe_strings(
                [
                    *_string_list(check.get("removed_subcommands")),
                    *_string_list(check.get("removed_dispatch_commands")),
                ]
            )
            for command in removed:
                lines.append(f"- Existing command {command} was removed in {path}.")

    lines.append("Repair must preserve all existing CLI commands and add the new command without replacing them.")
    return "\n".join(lines)


def _evidence_used(
    session_path: Path,
    *,
    sandbox_test_results: Any,
    working_tree_test_results: Any,
    llm_review: Any,
) -> list[str]:
    candidates = [
        "user_request.txt",
        "plan.json",
        "plan.md",
        "file_changes.json",
        "diff.patch",
        "semantic_review.json",
        "cli_regression_check.json",
        "plan_constraints_check.json",
        "diff_warnings.json",
    ]

    if isinstance(sandbox_test_results, dict):
        candidates.extend(["sandbox_test_results.json", "sandbox_test_output.log"])

    if isinstance(working_tree_test_results, dict):
        candidates.extend(["working_tree_test_results.json", "working_tree_test_output.log"])

    if isinstance(llm_review, dict):
        candidates.append("llm_review.json")

    return [name for name in candidates if (session_path / name).exists()]


def _normalize_relative_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/")

    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]

    pure_path = PurePosixPath(normalized)

    if pure_path.is_absolute() or normalized.startswith("/") or _has_windows_drive(normalized):
        raise DiffError(f"Refusing to read repair context for absolute path: {normalized}")

    if ".." in pure_path.parts:
        raise DiffError(f"Refusing to read repair context for path traversal: {normalized}")

    return str(pure_path)


def _has_windows_drive(path: str) -> bool:
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()


def _numbered_content(content: str) -> str:
    lines = content.splitlines()

    if not lines:
        return ""

    return "\n".join(f"{index} | {line}" for index, line in enumerate(lines, start=1))


def _limit_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text.rstrip("\n")
    return "\n".join(lines[:max_lines])


def _tail_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text.rstrip("\n")
    return "\n".join(lines[-max_lines:])


def _read_optional_session_text(session: ForgeSession, file_name: str) -> str:
    try:
        return read_session_text(session, file_name)
    except SessionError:
        return ""


def _read_optional_file_text(path: Path) -> str | None:
    if not path.exists():
        return None

    return path.read_text(encoding="utf-8")


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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value in seen:
            continue
        deduped.append(value)
        seen.add(value)

    return deduped


def _next_repair_count(session_path: Path) -> int:
    metadata = _read_json_file(session_path / "repair_metadata.json")

    if not isinstance(metadata, dict):
        return 1

    repair_count = metadata.get("repair_count")

    if not isinstance(repair_count, int) or repair_count < 0:
        return 1

    return repair_count + 1
