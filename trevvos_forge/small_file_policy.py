from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput


SMALL_FILE_LINE_LIMIT = 120
LOCAL_STRUCTURAL_OPERATIONS = {"append_to_file", "insert_after_line"}
ENTRYPOINT_NAMES = {"main.py", "cli.py", "app.py", "__main__.py"}
STRUCTURAL_TERMS = {
    "argparse",
    "cli",
    "command",
    "dispatch",
    "entrypoint",
    "main",
    "parser",
    "parse_args",
    "refactor",
    "reorganize",
    "reorganizar",
    "reestruturar",
    "subcommand",
    "subparser",
}


def detect_small_file_structural_edit_risk(
    *,
    file_changes: FileChangesOutput,
    repo_root: Path,
    plan: dict[str, Any] | None = None,
    request: str | None = None,
) -> list[str]:
    warnings: list[str] = []
    changes_by_path: dict[str, list[FileChange]] = defaultdict(list)

    for change in file_changes.changes:
        changes_by_path[_normalize_path(change.path)].append(change)

    plan_text = _plan_text(plan, request)

    for path, changes in changes_by_path.items():
        metadata = _file_metadata(repo_root=repo_root, path=path, changes=changes)
        if not metadata["is_small"]:
            continue

        if not path.endswith(".py"):
            continue

        structural = _is_structural_path(path) or _contains_structural_terms(plan_text)
        structural = structural or any(_change_mentions_structure(change) for change in changes)

        if not structural:
            continue

        local_ops = [
            change.operation
            for change in changes
            if change.mode == "operation_based_edit" and change.operation in LOCAL_STRUCTURAL_OPERATIONS
        ]
        has_full_rewrite = any(change.mode == "full_file_rewrite" for change in changes)
        has_replace_block = any(change.operation == "replace_block" for change in changes)

        if len(local_ops) >= 2:
            warnings.append(
                f"Small file structural edit risk: {path} is a small CLI file and received multiple local insert/append operations. Consider full_file_rewrite or replace_block to preserve structure."
            )

        if (
            metadata["has_main_guard"]
            and any(change.operation == "append_to_file" for change in changes)
        ):
            warnings.append(
                f"Small file structural edit risk: {path} received append_to_file after an if __name__ == \"__main__\" guard. Consider full_file_rewrite or replace_block so helpers, parser setup, and dispatch stay in the right order."
            )

        if (
            _is_structural_path(path)
            and any(change.operation == "append_to_file" for change in changes)
            and any(_change_mentions_parser_or_command(change) for change in changes)
        ):
            warnings.append(
                f"Small file structural edit risk: {path} is a small entrypoint and parser/command code was appended. Prefer full_file_rewrite or replace_block for CLI structure changes."
            )

        if not has_full_rewrite and not has_replace_block and any(local_ops):
            warnings.append(
                f"Small file structural edit risk: {path} is small and appears to receive a structural change without full_file_rewrite or replace_block. Consider a controlled rewrite or a wider replace_block."
            )

    return _dedupe_strings(warnings)


def _file_metadata(*, repo_root: Path, path: str, changes: list[FileChange]) -> dict[str, Any]:
    existing_content = _read_existing_content(repo_root, path)
    content = existing_content

    if content is None:
        content = "\n".join(change.content for change in changes if isinstance(change.content, str))

    lines = content.splitlines() if content else []

    return {
        "line_count": len(lines),
        "is_small": len(lines) <= SMALL_FILE_LINE_LIMIT,
        "has_main_guard": '__name__ == "__main__"' in content or "__name__ == '__main__'" in content,
    }


def _read_existing_content(repo_root: Path, path: str) -> str | None:
    target = (repo_root / path).resolve()

    try:
        target.relative_to(repo_root.resolve())
    except ValueError:
        return None

    if not target.exists() or not target.is_file():
        return None

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _normalize_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/")
    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]
    return str(PurePosixPath(normalized))


def _is_structural_path(path: str) -> bool:
    return PurePosixPath(path).name.lower() in ENTRYPOINT_NAMES


def _plan_text(plan: dict[str, Any] | None, request: str | None) -> str:
    parts: list[str] = []

    if request:
        parts.append(request)

    if isinstance(plan, dict):
        for value in plan.values():
            if isinstance(value, list):
                parts.extend(item for item in value if isinstance(item, str))
            elif isinstance(value, str):
                parts.append(value)

    return "\n".join(parts).lower()


def _contains_structural_terms(text: str) -> bool:
    return any(term in text for term in STRUCTURAL_TERMS)


def _change_mentions_structure(change: FileChange) -> bool:
    return _contains_structural_terms(_change_text(change))


def _change_mentions_parser_or_command(change: FileChange) -> bool:
    text = _change_text(change)
    return any(term in text for term in ["add_parser", "subparser", "argparse", "parse_args", "dispatch"])


def _change_text(change: FileChange) -> str:
    return "\n".join(
        value
        for value in [change.content, change.insert, change.replacement, change.target]
        if isinstance(value, str)
    ).lower()


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value in seen:
            continue
        deduped.append(value)
        seen.add(value)

    return deduped
