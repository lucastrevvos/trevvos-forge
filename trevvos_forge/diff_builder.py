import difflib
from pathlib import Path, PurePosixPath

from trevvos_forge.exceptions import DiffError
from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput


def build_unified_diff_from_file_changes(
    *,
    workspace_root: Path,
    file_changes: FileChangesOutput,
    warnings: list[str] | None = None,
) -> str:
    resolved_root = workspace_root.resolve()
    patch_parts: list[str] = []

    for change in file_changes.changes:
        relative_path = _normalize_change_path(change.path)
        file_patch = _build_file_diff(
            workspace_root=resolved_root,
            relative_path=relative_path,
            change=change,
            warnings=warnings,
        )

        if file_patch:
            patch_parts.append(file_patch)

    if not patch_parts:
        raise DiffError("No actual file changes were generated from the model output.")

    return "\n".join(patch_parts).rstrip("\n") + "\n"


def _build_file_diff(
    *,
    workspace_root: Path,
    relative_path: str,
    change: FileChange,
    warnings: list[str] | None,
) -> str:
    target_path = (workspace_root / relative_path).resolve()

    try:
        target_path.relative_to(workspace_root)
    except ValueError as exc:
        raise DiffError(f"Refusing to build diff for path outside workspace: {relative_path}") from exc

    if change.change_type == "modified":
        if not target_path.exists():
            raise DiffError(f"Cannot modify missing file: {relative_path}")

        if not target_path.is_file():
            raise DiffError(f"Cannot modify non-file path: {relative_path}")

        try:
            old_content = target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise DiffError(f"Cannot build diff for non-UTF-8 file: {relative_path}") from exc
        except PermissionError as exc:
            raise DiffError(f"Permission denied while reading file: {relative_path}") from exc

        old_lines = _content_to_lines(old_content)
        new_lines = _complete_possible_truncated_content(
            relative_path=relative_path,
            old_lines=old_lines,
            new_lines=_content_to_lines(change.content),
            warnings=warnings,
        )
        fromfile = f"a/{relative_path}"
    elif change.change_type == "created":
        if target_path.exists():
            raise DiffError(f"Cannot create file because it already exists: {relative_path}")

        old_lines = []
        new_lines = _content_to_lines(change.content)
        fromfile = "/dev/null"
    else:
        raise DiffError(f"Unsupported file change type: {change.change_type}")

    tofile = f"b/{relative_path}"

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=fromfile,
            tofile=tofile,
            lineterm="\n",
        )
    )

    if not diff_lines:
        return ""

    header_lines = [f"diff --git a/{relative_path} b/{relative_path}"]

    if change.change_type == "created":
        header_lines.append("new file mode 100644")

    return "\n".join(header_lines) + "\n" + "".join(diff_lines).rstrip("\n")


def _content_to_lines(content: str) -> list[str]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    if normalized and not normalized.endswith("\n"):
        normalized += "\n"

    return normalized.splitlines(keepends=True)


def _complete_possible_truncated_content(
    *,
    relative_path: str,
    old_lines: list[str],
    new_lines: list[str],
    warnings: list[str] | None,
) -> list[str]:
    if not old_lines or not new_lines or len(new_lines) >= len(old_lines):
        return new_lines

    completed_lines = _append_unchanged_tail_if_omitted(
        old_lines=old_lines,
        new_lines=new_lines,
    )

    if len(completed_lines) > len(new_lines) and warnings is not None:
        warnings.append(
            "WARNING: LLM output appears truncated. Forge preserved the unchanged "
            f"file tail automatically for {relative_path}. Review the generated patch before applying."
        )

    removed_line_count = len(old_lines) - len(completed_lines)

    if removed_line_count > 10 and len(completed_lines) < int(len(old_lines) * 0.75):
        raise DiffError(
            "Refusing to build diff because the generated final content appears "
            f"truncated for modified file: {relative_path}"
        )

    return completed_lines


def _append_unchanged_tail_if_omitted(*, old_lines: list[str], new_lines: list[str]) -> list[str]:
    anchor_line = new_lines[-1]

    for old_index in range(len(old_lines) - 1, -1, -1):
        if old_lines[old_index] == anchor_line:
            return new_lines + old_lines[old_index + 1 :]

    return new_lines


def _normalize_change_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/")

    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]

    if not normalized:
        raise DiffError("Refusing to build diff for empty path.")

    pure_path = PurePosixPath(normalized)

    if pure_path.is_absolute() or normalized.startswith("/") or _has_windows_drive(normalized):
        raise DiffError(f"Refusing to build diff for absolute path: {normalized}")

    if ".." in pure_path.parts:
        raise DiffError(f"Refusing to build diff for path traversal: {normalized}")

    return str(pure_path)


def _has_windows_drive(path: str) -> bool:
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()
