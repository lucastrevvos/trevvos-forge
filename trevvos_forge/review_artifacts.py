from trevvos_forge.file_change_outputs import FileChangesOutput


SEMANTIC_REVIEW_NOTE = (
    "This review summarizes the generated patch but does not prove semantic correctness."
)


def build_change_summary_markdown(
    *,
    request: str | None,
    file_changes: FileChangesOutput,
    warnings: list[str],
    safety_validation: str = "passed",
    git_apply_check: str = "passed",
    plan_constraints_status: str = "not_run",
) -> str:
    request_text = request.strip() if request and request.strip() else "Request unavailable in session metadata."
    files_changed = "\n".join(
        f"- `{change.path}` — {change.change_type} — {_change_descriptor(change)}"
        for change in file_changes.changes
    ) or "- None"
    patch_summary = "\n".join(
        f"- {_summarize_change(change)}"
        for change in file_changes.changes
    ) or "- No file changes."
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- None"

    return f"""# Change Summary

## Request

{request_text}

## Files Changed

{files_changed}

## Patch Summary

{patch_summary}

## Validations

- Forge safety validation: {safety_validation}
- git apply --check: {git_apply_check}
- Plan constraints: {plan_constraints_status}

## Warnings

{warning_lines}
""".strip() + "\n"


def build_semantic_review_json(
    *,
    request: str | None,
    file_changes: FileChangesOutput,
    warnings: list[str],
    safety_validation: str = "passed",
    git_apply_check: str = "passed",
    plan_constraints_status: str = "not_run",
) -> dict:
    return {
        "review_type": "deterministic",
        "status": "informational"
        if safety_validation == "passed" and git_apply_check == "passed"
        else "validation_failed",
        "request_available": bool(request and request.strip()),
        "files_changed": [
            {
                "path": change.path,
                "change_type": change.change_type,
                "mode": change.mode,
                "operation": change.operation,
            }
            for change in file_changes.changes
        ],
        "validations": {
            "safety_validation": safety_validation,
            "git_apply_check": git_apply_check,
            "plan_constraints": plan_constraints_status,
        },
        "warnings": warnings,
        "notes": [
            SEMANTIC_REVIEW_NOTE,
        ],
    }


def build_patch_preview(patch_text: str, max_lines: int = 80) -> tuple[str, bool]:
    lines = patch_text.splitlines()

    if len(lines) <= max_lines:
        return patch_text.rstrip("\n"), False

    return "\n".join(lines[:max_lines]), True


def _change_descriptor(change) -> str:
    if change.mode == "operation_based_edit":
        return f"{change.mode} / {change.operation}"

    return change.mode


def _summarize_change(change) -> str:
    if change.operation == "insert_after_heading":
        return f"Inserted content after heading `{change.target}` in `{change.path}`."

    if change.operation == "insert_after_line":
        return f"Inserted content after line `{change.target}` in `{change.path}`."

    if change.operation == "replace_exact_text":
        return f"Replaced exact text in `{change.path}`."

    if change.operation == "create_file":
        return f"Created `{change.path}`."

    if change.change_type == "created":
        return f"Created `{change.path}`."

    return f"Updated `{change.path}`."
