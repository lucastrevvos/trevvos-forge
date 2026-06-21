import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from trevvos_forge.exceptions import DiffValidationError
from trevvos_forge.sessions import ForgeSession, read_session_text
from trevvos_forge.workspace import IGNORED_DIRS, SENSITIVE_FILES


@dataclass(frozen=True)
class PatchFileChange:
    path: str
    change_type: str


@dataclass(frozen=True)
class DiffValidationResult:
    is_valid: bool
    changes: list[PatchFileChange]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "changes": [asdict(change) for change in self.changes],
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class _ParsedPatchFile:
    old_path: str | None
    new_path: str | None
    is_created: bool
    is_deleted: bool


def validate_diff_patch(
    *,
    workspace_root: Path,
    session: ForgeSession,
    diff_text: str,
) -> DiffValidationResult:
    cleaned_diff = diff_text.strip()

    if not cleaned_diff:
        raise DiffValidationError("Diff rejected: patch is empty.")

    if not _looks_like_unified_diff(cleaned_diff):
        raise DiffValidationError("Diff rejected: patch does not look like a unified diff.")

    if _contains_binary_patch(cleaned_diff):
        raise DiffValidationError("Diff rejected: binary patches are not supported.")

    selected_paths = _load_selected_paths(session)
    parsed_files = _parse_patch_files(cleaned_diff)

    if not parsed_files:
        raise DiffValidationError("Diff rejected: no changed files were found in the patch.")

    resolved_root = workspace_root.resolve()
    changes: list[PatchFileChange] = []
    seen_paths: set[str] = set()
    modified_outside_context: list[str] = []

    for parsed_file in parsed_files:
        if parsed_file.is_deleted:
            target_path = parsed_file.old_path or parsed_file.new_path or "unknown"
            raise DiffValidationError(f"Diff rejected: deletion attempts are not allowed: {target_path}")

        raw_path = parsed_file.new_path or parsed_file.old_path

        if raw_path is None:
            raise DiffValidationError("Diff rejected: patch contains a file without a target path.")

        normalized_path = _normalize_patch_path(raw_path)
        _validate_safe_relative_path(
            workspace_root=resolved_root,
            relative_path=normalized_path,
        )

        if normalized_path in seen_paths:
            continue

        seen_paths.add(normalized_path)

        absolute_path = (resolved_root / normalized_path).resolve()
        change_type = "created" if parsed_file.is_created or not absolute_path.exists() else "modified"

        if change_type == "modified" and normalized_path not in selected_paths:
            modified_outside_context.append(normalized_path)
            continue

        changes.append(
            PatchFileChange(
                path=normalized_path,
                change_type=change_type,
            )
        )

    if modified_outside_context:
        paths = ", ".join(sorted(modified_outside_context))
        raise DiffValidationError(
            f"Diff rejected: patch modifies files not included in selected context: {paths}"
        )

    if not changes:
        raise DiffValidationError("Diff rejected: no safe file changes were found in the patch.")

    return DiffValidationResult(
        is_valid=True,
        changes=changes,
        warnings=[],
    )


def _load_selected_paths(session: ForgeSession) -> set[str]:
    try:
        raw_selected_files = json.loads(read_session_text(session, "selected_files.json"))
    except json.JSONDecodeError as exc:
        raise DiffValidationError("Diff rejected: selected_files.json is invalid JSON.") from exc

    selected_files = raw_selected_files.get("selected_files")

    if not isinstance(selected_files, list):
        raise DiffValidationError("Diff rejected: selected_files.json has no selected_files list.")

    selected_paths: set[str] = set()

    for item in selected_files:
        if not isinstance(item, dict):
            continue

        path = item.get("path")

        if isinstance(path, str) and path.strip():
            selected_paths.add(_normalize_selected_path(path))

    return selected_paths


def _parse_patch_files(diff_text: str) -> list[_ParsedPatchFile]:
    lines = diff_text.splitlines()
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        if line.startswith("diff --git "):
            if current_block:
                blocks.append(current_block)
            current_block = [line]
        elif current_block:
            current_block.append(line)

    if current_block:
        blocks.append(current_block)

    if not blocks:
        blocks = [lines]

    parsed_files: list[_ParsedPatchFile] = []

    for block in blocks:
        parsed_file = _parse_patch_block(block)

        if parsed_file is not None:
            parsed_files.append(parsed_file)

    return parsed_files


def _parse_patch_block(block: list[str]) -> _ParsedPatchFile | None:
    old_path: str | None = None
    new_path: str | None = None
    is_created = False
    is_deleted = False

    first_line = block[0] if block else ""

    if first_line.startswith("diff --git "):
        parts = first_line.split()

        if len(parts) >= 4:
            old_path = parts[2]
            new_path = parts[3]

    for line in block:
        if line.startswith("new file mode "):
            is_created = True
        elif line.startswith("deleted file mode "):
            is_deleted = True
        elif line.startswith("--- "):
            old_path = line[4:].split("\t", 1)[0].strip()
        elif line.startswith("+++ "):
            new_path = line[4:].split("\t", 1)[0].strip()

    if old_path == "/dev/null":
        is_created = True

    if new_path == "/dev/null":
        is_deleted = True

    if old_path is None and new_path is None:
        return None

    return _ParsedPatchFile(
        old_path=old_path,
        new_path=new_path,
        is_created=is_created,
        is_deleted=is_deleted,
    )


def _normalize_selected_path(path: str) -> str:
    return path.strip().replace("\\", "/").lstrip("/")


def _normalize_patch_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/")

    if normalized == "/dev/null":
        raise DiffValidationError("Diff rejected: /dev/null cannot be used as a target file.")

    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]

    if not normalized:
        raise DiffValidationError("Diff rejected: patch contains an empty path.")

    pure_path = PurePosixPath(normalized)

    if pure_path.is_absolute() or normalized.startswith("/") or _has_windows_drive(normalized):
        raise DiffValidationError(f"Diff rejected: absolute paths are not allowed: {normalized}")

    if ".." in pure_path.parts:
        raise DiffValidationError(f"Diff rejected: path traversal is not allowed: {normalized}")

    return str(pure_path)


def _validate_safe_relative_path(*, workspace_root: Path, relative_path: str) -> None:
    pure_path = PurePosixPath(relative_path)

    if not pure_path.parts:
        raise DiffValidationError("Diff rejected: patch contains an empty path.")

    ignored_part = next((part for part in pure_path.parts if part in IGNORED_DIRS), None)

    if ignored_part is not None:
        raise DiffValidationError(
            f"Diff rejected: patch targets ignored directory '{ignored_part}': {relative_path}"
        )

    if pure_path.name in SENSITIVE_FILES:
        raise DiffValidationError(f"Diff rejected: patch targets sensitive file: {relative_path}")

    resolved_path = (workspace_root / relative_path).resolve()

    try:
        resolved_path.relative_to(workspace_root)
    except ValueError as exc:
        raise DiffValidationError(
            f"Diff rejected: path is outside the workspace root: {relative_path}"
        ) from exc


def _looks_like_unified_diff(text: str) -> bool:
    return (
        "diff --git " in text
        or ("--- " in text and "+++ " in text)
        or "@@ " in text
    )


def _contains_binary_patch(text: str) -> bool:
    return any(
        line.startswith("Binary files ") or line == "GIT binary patch"
        for line in text.splitlines()
    )


def _has_windows_drive(path: str) -> bool:
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()
