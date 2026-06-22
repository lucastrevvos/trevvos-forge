import json
from pathlib import Path, PurePosixPath
from typing import Any

from trevvos_forge.exceptions import DiffError
from trevvos_forge.file_change_outputs import FileChangesOutput


CONSTRAINT_KEYS = [
    "expected_behavior",
    "acceptance_criteria",
    "suggested_verification_commands",
    "files_to_create",
    "files_to_modify",
    "files_not_to_modify",
]


def load_plan_constraints(session_dir: Path) -> dict:
    plan_path = session_dir / "plan.json"

    if not plan_path.exists():
        return _empty_constraints()

    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DiffError("Session plan.json is invalid JSON.") from exc

    if not isinstance(payload, dict):
        return _empty_constraints()

    constraints = _empty_constraints()

    for key in CONSTRAINT_KEYS:
        constraints[key] = _string_list(payload.get(key))

    constraints["files_to_create"] = _normalize_path_list(constraints["files_to_create"])
    constraints["files_to_modify"] = _normalize_path_list(constraints["files_to_modify"])
    constraints["files_not_to_modify"] = _normalize_path_list(constraints["files_not_to_modify"])

    return constraints


def build_plan_constraints_prompt_section(constraints: dict) -> str:
    return f"""Plan constraints

Expected behavior:
{_bullet_lines(constraints.get("expected_behavior"))}

Acceptance criteria:
{_bullet_lines(constraints.get("acceptance_criteria"))}

Suggested verification commands:
{_bullet_lines(constraints.get("suggested_verification_commands"))}

Files to create:
{_bullet_lines(constraints.get("files_to_create"))}

Files to modify:
{_bullet_lines(constraints.get("files_to_modify"))}

Files not to modify:
{_bullet_lines(constraints.get("files_not_to_modify"))}

Rules:
- Treat Files not to modify as hard constraints.
- Do not modify files listed in Files not to modify.
- Prefer creating files listed in Files to create.
- Prefer modifying only files listed in Files to modify.
- If the plan says to create a CLI, implement executable behavior matching expected behavior.
- Do not merely list functions when the expected behavior requires executable commands.
- If the requested change cannot be completed while respecting constraints, return a structured error instead of inventing changes.
""".strip()


def check_file_changes_against_plan_constraints(
    *,
    file_changes: FileChangesOutput,
    constraints: dict,
) -> dict:
    files_changed = [_normalize_path(change.path) for change in file_changes.changes]
    files_created = [
        _normalize_path(change.path)
        for change in file_changes.changes
        if change.change_type == "created"
    ]
    files_to_create = _normalize_path_list(_string_list(constraints.get("files_to_create")))
    files_to_modify = _normalize_path_list(_string_list(constraints.get("files_to_modify")))
    files_not_to_modify = _normalize_path_list(_string_list(constraints.get("files_not_to_modify")))

    violations: list[str] = []
    warnings: list[str] = []

    for path in files_changed:
        if path in files_not_to_modify:
            violations.append(f"{path} is marked as files_not_to_modify.")

    if files_to_create and not any(path in files_created for path in files_to_create):
        expected = ", ".join(files_to_create)
        warnings.append(f"Plan expected creation of {expected}, but it was not created.")

    if files_to_modify:
        allowed = set(files_to_modify) | set(files_to_create)

        for path in files_changed:
            if path not in allowed and path not in files_not_to_modify:
                warnings.append(f"{path} is outside files_to_modify and files_to_create from the plan.")

    status = "failed" if violations else "warning" if warnings else "passed"

    return {
        "status": status,
        "files_changed": files_changed,
        "files_to_create": files_to_create,
        "files_to_modify": files_to_modify,
        "files_not_to_modify": files_not_to_modify,
        "violations": violations,
        "warnings": warnings,
    }


def write_plan_constraints_check(session_dir: Path, result: dict) -> None:
    (session_dir / "plan_constraints_check.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _empty_constraints() -> dict:
    return {key: [] for key in CONSTRAINT_KEYS}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _normalize_path_list(paths: list[str]) -> list[str]:
    normalized: list[str] = []

    for path in paths:
        normalized_path = _normalize_path(path)

        if normalized_path not in normalized:
            normalized.append(normalized_path)

    return normalized


def _normalize_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/")

    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]

    return str(PurePosixPath(normalized))


def _bullet_lines(value: Any) -> str:
    items = _string_list(value)

    if not items:
        return "- none"

    return "\n".join(f"- {item}" for item in items)
