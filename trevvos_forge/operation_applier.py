from dataclasses import dataclass
from pathlib import Path

from trevvos_forge.exceptions import DiffError
from trevvos_forge.file_change_outputs import FileChange


@dataclass(frozen=True)
class OperationApplyResult:
    path: str
    original_content: str | None
    new_content: str
    warnings: list[str]


def apply_operation_change(change: FileChange, repo_root: Path) -> OperationApplyResult:
    if change.mode != "operation_based_edit":
        raise DiffError(f"Unsupported operation mode: {change.mode}")

    target_path = (repo_root / change.path).resolve()

    try:
        target_path.relative_to(repo_root)
    except ValueError as exc:
        raise DiffError(f"Refusing to apply operation outside workspace: {change.path}") from exc

    if change.operation == "create_file":
        return _apply_create_file(change=change, target_path=target_path)

    if not target_path.exists():
        raise DiffError(f"Cannot apply operation to missing file: {change.path}")

    if not target_path.is_file():
        raise DiffError(f"Cannot apply operation to non-file path: {change.path}")

    try:
        original_content = target_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DiffError(f"Cannot apply operation to non-UTF-8 file: {change.path}") from exc
    except PermissionError as exc:
        raise DiffError(f"Permission denied while reading file: {change.path}") from exc

    return apply_operation_change_to_content(
        change=change,
        original_content=original_content,
        current_content=original_content,
        path=change.path,
    )


def apply_operation_change_to_content(
    *,
    change: FileChange,
    original_content: str | None,
    current_content: str | None,
    path: str | None = None,
) -> OperationApplyResult:
    if change.mode != "operation_based_edit":
        raise DiffError(f"Unsupported operation mode: {change.mode}")

    display_path = path or change.path

    if change.operation == "create_file":
        if original_content is not None or current_content is not None:
            raise DiffError(f"Cannot create file after existing content was loaded: {display_path}")

        return OperationApplyResult(
            path=display_path,
            original_content=None,
            new_content=_ensure_final_newline(_required_value(change.content, "content")),
            warnings=[],
        )

    if current_content is None:
        raise DiffError(f"Cannot apply operation to missing file: {display_path}")

    if change.operation == "insert_after_heading":
        new_content = _insert_after_unique_line(
            content=current_content,
            target=_required_value(change.target, "target"),
            insert=_required_value(change.insert, "insert"),
            path=display_path,
            operation="insert_after_heading",
            markdown_spacing=True,
        )
    elif change.operation == "insert_after_line":
        new_content = _insert_after_unique_line(
            content=current_content,
            target=_required_value(change.target, "target"),
            insert=_required_value(change.insert, "insert"),
            path=display_path,
            operation="insert_after_line",
            markdown_spacing=False,
        )
    elif change.operation == "insert_before_line":
        new_content = _insert_before_unique_line(
            content=current_content,
            target=_required_value(change.target, "target"),
            insert=_required_value(change.insert, "insert"),
            path=display_path,
            operation="insert_before_line",
        )
    elif change.operation == "replace_exact_text":
        new_content = _replace_exact_text(
            content=current_content,
            target=_required_value(change.target, "target"),
            replacement=_required_value(change.replacement, "replacement"),
            path=display_path,
            operation="replace_exact_text",
        )
    elif change.operation == "replace_block":
        new_content = _replace_exact_text(
            content=current_content,
            target=_required_value(change.target, "target"),
            replacement=_required_value(change.replacement, "replacement"),
            path=display_path,
            operation="replace_block",
        )
    elif change.operation == "append_to_file":
        new_content = _append_to_file(
            content=current_content,
            insert=_required_value(change.insert, "insert"),
        )
    else:
        raise DiffError(f"Unsupported operation: {change.operation}")

    return OperationApplyResult(
        path=display_path,
        original_content=original_content,
        new_content=new_content,
        warnings=[],
    )


def _apply_create_file(*, change: FileChange, target_path: Path) -> OperationApplyResult:
    if target_path.exists():
        raise DiffError(f"Cannot create file because it already exists: {change.path}")

    return OperationApplyResult(
        path=change.path,
        original_content=None,
        new_content=_ensure_final_newline(_required_value(change.content, "content")),
        warnings=[],
    )


def _insert_after_unique_line(
    *,
    content: str,
    target: str,
    insert: str,
    path: str,
    operation: str,
    markdown_spacing: bool,
) -> str:
    lines = content.splitlines(keepends=True)
    matches = [
        index
        for index, line in enumerate(lines)
        if line.strip() == target.strip()
    ]

    if not matches:
        raise DiffError(f"Operation {operation} target not found in {path}: {target}")

    if len(matches) > 1:
        raise DiffError(f"Operation {operation} target is ambiguous in {path}: {target}")

    insert_lines = _insert_text_to_lines(insert)
    insert_index = matches[0] + 1

    if markdown_spacing:
        if insert_index < len(lines) and lines[insert_index].strip() == "":
            insert_index += 1
            insert_lines = insert_lines + ["\n"]
        else:
            insert_lines = _markdown_insert_block(insert_lines)

    return "".join(lines[:insert_index] + insert_lines + lines[insert_index:])


def _insert_before_unique_line(
    *,
    content: str,
    target: str,
    insert: str,
    path: str,
    operation: str,
) -> str:
    lines = content.splitlines(keepends=True)
    matches = [
        index
        for index, line in enumerate(lines)
        if line.strip() == target.strip()
    ]

    if not matches:
        raise DiffError(f"Operation {operation} target not found in {path}: {target}")

    if len(matches) > 1:
        raise DiffError(f"Operation {operation} target is ambiguous in {path}: {target}")

    insert_lines = _insert_text_to_lines(insert)
    insert_index = matches[0]

    return "".join(lines[:insert_index] + insert_lines + lines[insert_index:])


def _replace_exact_text(
    *,
    content: str,
    target: str,
    replacement: str,
    path: str,
    operation: str,
) -> str:
    occurrence_count = content.count(target)

    if occurrence_count == 0:
        raise DiffError(f"Operation {operation} target not found in {path}: {target}")

    if occurrence_count > 1:
        raise DiffError(f"Operation {operation} target is ambiguous in {path}: {target}")

    return content.replace(target, replacement, 1)


def _append_to_file(*, content: str, insert: str) -> str:
    append_text = _ensure_final_newline(insert)

    if content.endswith("\n"):
        while append_text.startswith("\n\n"):
            append_text = append_text[1:]

        return content + append_text

    if append_text.startswith("\n"):
        return content + append_text

    return content + "\n" + append_text


def _insert_text_to_lines(insert: str) -> list[str]:
    text = _ensure_final_newline(insert)

    return text.splitlines(keepends=True)


def _markdown_insert_block(insert_lines: list[str]) -> list[str]:
    return ["\n"] + insert_lines + ["\n"]


def _ensure_final_newline(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    if normalized and not normalized.endswith("\n"):
        normalized += "\n"

    return normalized


def _required_value(value: str | None, field_name: str) -> str:
    if value is None:
        raise DiffError(f"Missing operation field: {field_name}")

    return value
