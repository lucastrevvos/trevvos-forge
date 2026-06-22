from typing import Any

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
    plan: dict[str, Any] | None = None,
    plan_constraints_check: dict[str, Any] | None = None,
    sandbox_test_results: dict[str, Any] | None = None,
    working_tree_test_results: dict[str, Any] | None = None,
) -> dict:
    return _semantic_review_payload(
        request_available=bool(request and request.strip()),
        files_changed=[
            {
                "path": change.path,
                "change_type": change.change_type,
                "mode": change.mode,
                "operation": change.operation,
            }
            for change in file_changes.changes
        ],
        warnings=warnings,
        safety_validation=safety_validation,
        git_apply_check=git_apply_check,
        plan_constraints_status=plan_constraints_status,
        plan=plan,
        plan_constraints_check=plan_constraints_check,
        sandbox_test_results=sandbox_test_results,
        working_tree_test_results=working_tree_test_results,
    )


def build_semantic_review_json_from_context(context: dict[str, Any]) -> dict:
    deterministic_review = context.get("deterministic_review")
    validations = (
        deterministic_review.get("validations")
        if isinstance(deterministic_review, dict)
        else {}
    )
    if not isinstance(validations, dict):
        validations = {}

    plan_constraints_check = context.get("plan_constraints_check")
    plan_constraints_status = validations.get("plan_constraints", "not_run")
    if isinstance(plan_constraints_check, dict):
        plan_constraints_status = plan_constraints_check.get("status", plan_constraints_status)

    files_changed = context.get("files_changed")
    if not isinstance(files_changed, list):
        files_changed = []

    warnings = context.get("warnings")
    if not isinstance(warnings, list):
        warnings = []

    return _semantic_review_payload(
        request_available=bool(context.get("request_available")),
        files_changed=[
            change
            for change in files_changed
            if isinstance(change, dict)
        ],
        warnings=[
            warning
            for warning in warnings
            if isinstance(warning, str)
        ],
        safety_validation=validations.get("safety_validation", "unknown"),
        git_apply_check=validations.get("git_apply_check", "unknown"),
        plan_constraints_status=plan_constraints_status,
        plan=context.get("plan") if isinstance(context.get("plan"), dict) else None,
        plan_constraints_check=plan_constraints_check if isinstance(plan_constraints_check, dict) else None,
        sandbox_test_results=(
            context.get("sandbox_test_results")
            if isinstance(context.get("sandbox_test_results"), dict)
            else None
        ),
        working_tree_test_results=(
            context.get("working_tree_test_results")
            if isinstance(context.get("working_tree_test_results"), dict)
            else None
        ),
    )


def render_deterministic_review_text(review: dict[str, Any]) -> str:
    plan_review = review.get("plan_review") if isinstance(review.get("plan_review"), dict) else {}
    test_evidence = review.get("test_evidence") if isinstance(review.get("test_evidence"), dict) else {}
    plan_constraints = review.get("plan_constraints") if isinstance(review.get("plan_constraints"), dict) else {}
    concerns = _string_list(review.get("concerns"))
    warnings = _string_list(review.get("warnings"))

    return f"""Plan evidence
  - Expected behavior: {plan_review.get("expected_behavior_count", 0)}
  - Acceptance criteria: {plan_review.get("acceptance_criteria_count", 0)}
  - Suggested verification commands: {plan_review.get("suggested_verification_commands_count", 0)}
  - Plan commands executed: {plan_review.get("plan_commands_executed", "unknown")}

Test evidence
  - Sandbox tests: {test_evidence.get("sandbox", "unknown")}
  - Working tree tests: {test_evidence.get("working_tree", "unknown")}

Plan constraints
  - Status: {plan_constraints.get("status", "unknown")}

Concerns
{_plain_list(concerns)}

Warnings
{_plain_list(warnings)}
""".strip()


def _semantic_review_payload(
    *,
    request_available: bool,
    files_changed: list[dict[str, Any]],
    warnings: list[str],
    safety_validation: str,
    git_apply_check: str,
    plan_constraints_status: str,
    plan: dict[str, Any] | None,
    plan_constraints_check: dict[str, Any] | None,
    sandbox_test_results: dict[str, Any] | None,
    working_tree_test_results: dict[str, Any] | None,
) -> dict:
    plan_review = _build_plan_review(
        plan=plan,
        sandbox_test_results=sandbox_test_results,
        working_tree_test_results=working_tree_test_results,
    )
    test_evidence = {
        "sandbox": _test_status(sandbox_test_results),
        "working_tree": _test_status(working_tree_test_results),
    }
    plan_constraints = {
        "status": _plan_constraints_status(
            plan_constraints_check,
            plan_constraints_status,
        ),
    }
    concerns, generated_warnings = _review_findings(
        plan=plan,
        plan_review=plan_review,
        test_evidence=test_evidence,
        plan_constraints=plan_constraints,
    )
    merged_warnings = _dedupe_strings([*warnings, *generated_warnings])

    return {
        "review_type": "deterministic",
        "status": "informational"
        if safety_validation == "passed" and git_apply_check == "passed"
        else "validation_failed",
        "request_available": request_available,
        "files_changed": files_changed,
        "validations": {
            "safety_validation": safety_validation,
            "git_apply_check": git_apply_check,
            "plan_constraints": plan_constraints["status"],
        },
        "plan_review": plan_review,
        "test_evidence": test_evidence,
        "plan_constraints": plan_constraints,
        "concerns": concerns,
        "warnings": merged_warnings,
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


def _build_plan_review(
    *,
    plan: dict[str, Any] | None,
    sandbox_test_results: dict[str, Any] | None,
    working_tree_test_results: dict[str, Any] | None,
) -> dict[str, Any]:
    expected_behavior = _string_list_from_dict(plan, "expected_behavior")
    acceptance_criteria = _string_list_from_dict(plan, "acceptance_criteria")
    commands = _string_list_from_dict(plan, "suggested_verification_commands")

    return {
        "expected_behavior_count": len(expected_behavior),
        "acceptance_criteria_count": len(acceptance_criteria),
        "suggested_verification_commands_count": len(commands),
        "plan_commands_executed": _plan_commands_executed(
            commands=commands,
            test_results=[sandbox_test_results, working_tree_test_results],
        ),
    }


def _review_findings(
    *,
    plan: dict[str, Any] | None,
    plan_review: dict[str, Any],
    test_evidence: dict[str, str],
    plan_constraints: dict[str, str],
) -> tuple[list[str], list[str]]:
    concerns: list[str] = []
    warnings: list[str] = []

    command_count = plan_review.get("suggested_verification_commands_count", 0)
    commands_executed = plan_review.get("plan_commands_executed", "unknown")

    if command_count and test_evidence.get("sandbox") == "not_run":
        warnings.append("Suggested verification commands exist, but sandbox tests were not run.")

    if command_count and commands_executed in {"no", "partial"}:
        warnings.append("Plan verification commands were not fully executed.")

    if test_evidence.get("sandbox") in {"failed", "timed_out"}:
        concerns.append(f"Sandbox tests {test_evidence['sandbox']}.")

    if test_evidence.get("working_tree") in {"failed", "timed_out"}:
        concerns.append(f"Working tree tests {test_evidence['working_tree']}.")

    if plan_constraints.get("status") == "failed":
        concerns.append("Plan constraints check failed.")

    if not _string_list_from_dict(plan, "acceptance_criteria"):
        warnings.append("No acceptance criteria were available in the plan.")

    return concerns, warnings


def _plan_commands_executed(
    *,
    commands: list[str],
    test_results: list[dict[str, Any] | None],
) -> str:
    if not commands:
        return "unknown"

    executed: set[str] = set()
    plan_source: set[str] = set()

    for result in test_results:
        if not isinstance(result, dict):
            continue

        command_sources = result.get("command_sources")
        if not isinstance(command_sources, dict):
            continue

        executed.update(_string_list(command_sources.get("executed")))
        plan_source.update(_string_list(command_sources.get("plan")))

    matched = [command for command in commands if command in executed or command in plan_source]

    if len(matched) == len(commands):
        return "yes"

    if matched:
        return "partial"

    return "no"


def _plan_constraints_status(
    plan_constraints_check: dict[str, Any] | None,
    fallback: str,
) -> str:
    if isinstance(plan_constraints_check, dict) and isinstance(plan_constraints_check.get("status"), str):
        return plan_constraints_check["status"]

    if fallback in {"passed", "warning", "failed", "missing", "unknown", "not_run"}:
        return fallback

    return "unknown"


def _test_status(test_results: dict[str, Any] | None) -> str:
    if not isinstance(test_results, dict):
        return "not_run"

    status = test_results.get("status")
    if isinstance(status, str) and status:
        return status

    return "unknown"


def _string_list_from_dict(data: dict[str, Any] | None, key: str) -> list[str]:
    if not isinstance(data, dict):
        return []

    return _string_list(data.get(key))


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


def _plain_list(items: list[str]) -> str:
    if not items:
        return "  - None"

    return "\n".join(f"  - {item}" for item in items)
