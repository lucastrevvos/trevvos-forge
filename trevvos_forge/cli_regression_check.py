import re
from pathlib import Path, PurePosixPath
from typing import Any

from trevvos_forge.exceptions import DiffError
from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput
from trevvos_forge.operation_applier import apply_operation_change_to_content
from trevvos_forge.sessions import ForgeSession, write_session_json


SUBCOMMAND_PATTERN = re.compile(r"\.add_parser\(\s*['\"]([^'\"]+)['\"]")
DISPATCH_PATTERN = re.compile(r"\b(?:if|elif)\s+args\.command\s*==\s*['\"]([^'\"]+)['\"]")


def extract_argparse_subcommands(content: str) -> list[str]:
    return _dedupe(SUBCOMMAND_PATTERN.findall(content))


def extract_dispatch_commands(content: str) -> list[str]:
    return _dedupe(DISPATCH_PATTERN.findall(content))


def check_cli_command_preservation(original_content: str, new_content: str, path: str) -> dict:
    original_subcommands = extract_argparse_subcommands(original_content)
    new_subcommands = extract_argparse_subcommands(new_content)
    original_dispatch = extract_dispatch_commands(original_content)
    new_dispatch = extract_dispatch_commands(new_content)

    removed_subcommands = sorted(set(original_subcommands) - set(new_subcommands))
    removed_dispatch_commands = sorted(set(original_dispatch) - set(new_dispatch))
    added_subcommands = sorted(set(new_subcommands) - set(original_subcommands))
    added_dispatch_commands = sorted(set(new_dispatch) - set(original_dispatch))

    warnings = []
    for command in sorted(set(removed_subcommands + removed_dispatch_commands)):
        warnings.append(f"Existing CLI command '{command}' appears to have been removed.")

    applicable = bool(original_subcommands or original_dispatch or new_subcommands or new_dispatch)
    status = "failed" if warnings else "passed" if applicable else "not_applicable"

    return {
        "status": status,
        "path": path,
        "original_subcommands": original_subcommands,
        "new_subcommands": new_subcommands,
        "original_dispatch_commands": original_dispatch,
        "new_dispatch_commands": new_dispatch,
        "removed_subcommands": removed_subcommands,
        "removed_dispatch_commands": removed_dispatch_commands,
        "added_subcommands": added_subcommands,
        "added_dispatch_commands": added_dispatch_commands,
        "warnings": warnings,
    }


def build_cli_regression_check(*, workspace_root: Path, file_changes: FileChangesOutput) -> dict:
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []

    for relative_path, changes in _changes_by_path(file_changes).items():
        if not relative_path.endswith(".py"):
            continue

        original_content, new_content = _compose_final_content(
            workspace_root=workspace_root,
            relative_path=relative_path,
            changes=changes,
        )
        if original_content is None:
            continue

        check = check_cli_command_preservation(original_content, new_content, relative_path)
        if check["status"] == "not_applicable":
            continue

        checks.append(check)
        warnings.extend(check["warnings"])

    status = "not_applicable"
    if any(check.get("status") == "failed" for check in checks):
        status = "failed"
    elif checks:
        status = "passed"

    return {
        "status": status,
        "checks": checks,
        "warnings": _dedupe(warnings),
    }


def write_cli_regression_check(session: ForgeSession, payload: dict) -> None:
    write_session_json(session, "cli_regression_check.json", payload)


def _changes_by_path(file_changes: FileChangesOutput) -> dict[str, list[FileChange]]:
    grouped: dict[str, list[FileChange]] = {}
    for change in file_changes.changes:
        relative_path = _normalize_change_path(change.path)
        grouped.setdefault(relative_path, []).append(change)
    return grouped


def _compose_final_content(
    *,
    workspace_root: Path,
    relative_path: str,
    changes: list[FileChange],
) -> tuple[str | None, str]:
    if not changes:
        raise DiffError(f"No file changes available for: {relative_path}")

    target_path = (workspace_root / relative_path).resolve()
    try:
        target_path.relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise DiffError(f"Refusing to check CLI regression outside workspace: {relative_path}") from exc

    modes = {change.mode for change in changes}
    if len(modes) > 1:
        raise DiffError(f"Cannot check CLI regression for mixed file change modes: {relative_path}")

    first = changes[0]
    if first.mode == "full_file_rewrite":
        if len(changes) > 1:
            raise DiffError(f"Cannot check CLI regression for multiple full rewrites: {relative_path}")
        if first.content is None:
            raise DiffError(f"Missing full file content for CLI regression check: {relative_path}")
        if first.change_type == "created":
            return None, first.content
        return _read_existing_text(target_path, relative_path), first.content

    if first.mode != "operation_based_edit":
        raise DiffError(f"Unsupported file change mode for CLI regression check: {first.mode}")

    original_content: str | None
    current_content: str | None
    if first.operation == "create_file":
        original_content = None
        current_content = None
    else:
        original_content = _read_existing_text(target_path, relative_path)
        current_content = original_content

    for index, change in enumerate(changes):
        if index > 0 and change.operation == "create_file":
            raise DiffError(f"create_file must be first for CLI regression check: {relative_path}")
        result = apply_operation_change_to_content(
            change=change,
            original_content=original_content,
            current_content=current_content,
            path=relative_path,
        )
        current_content = result.new_content

    if current_content is None:
        raise DiffError(f"No final content for CLI regression check: {relative_path}")

    return original_content, current_content


def _read_existing_text(path: Path, relative_path: str) -> str:
    if not path.exists():
        raise DiffError(f"Cannot check CLI regression for missing file: {relative_path}")
    if not path.is_file():
        raise DiffError(f"Cannot check CLI regression for non-file path: {relative_path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DiffError(f"Cannot check CLI regression for non-UTF-8 file: {relative_path}") from exc


def _normalize_change_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/")
    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]
    pure_path = PurePosixPath(normalized)
    if pure_path.is_absolute() or normalized.startswith("/") or ".." in pure_path.parts:
        raise DiffError(f"Refusing to check CLI regression for unsafe path: {normalized}")
    return str(pure_path)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
