import json
from pathlib import Path
from typing import Any

from trevvos_forge.prompt_catalog import get_prompt


INFORMATIONAL_NOTE = (
    "This review is informational and does not prove semantic correctness."
)
ALLOWED_VERDICTS = {"appears_ok", "needs_human_review", "has_concerns", "blocked"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high", "unknown"}
ALLOWED_REQUEST_ALIGNMENTS = {
    "appears_aligned",
    "partially_aligned",
    "not_aligned",
    "unknown",
}


def build_review_context(
    session_dir: Path,
    max_patch_lines: int = 200,
    max_test_log_lines: int = 120,
) -> dict:
    evidence_used: list[str] = []
    request = _read_optional_text(session_dir / "user_request.txt")
    plan = _read_optional_text(session_dir / "plan.md")
    diff_patch = _read_optional_text(session_dir / "diff.patch")
    change_summary = _read_optional_text(session_dir / "change_summary.md")
    deterministic_review = _read_optional_json(session_dir / "semantic_review.json")
    file_changes = _read_optional_json(session_dir / "file_changes.json")
    diff_warnings = _read_optional_json(session_dir / "diff_warnings.json")
    test_results = _read_optional_json(session_dir / "test_results.json")
    test_output = _read_optional_text(session_dir / "test_output.log")
    metadata = _read_optional_json(session_dir / "metadata.json")

    if request is not None:
        evidence_used.append("user_request.txt")

    if plan is not None:
        evidence_used.append("plan.md")

    patch_preview, patch_truncated = _limit_lines(diff_patch or "", max_patch_lines)

    if diff_patch is not None:
        evidence_used.append("diff.patch")

    if change_summary is not None:
        evidence_used.append("change_summary.md")

    if deterministic_review is not None:
        evidence_used.append("semantic_review.json")

    if test_results is not None:
        evidence_used.append("test_results.json")

    test_output_tail, test_output_truncated = _tail_lines(test_output or "", max_test_log_lines)

    if test_output is not None:
        evidence_used.append("test_output.log")

    warnings = []

    if isinstance(diff_warnings, dict) and isinstance(diff_warnings.get("warnings"), list):
        warnings = [
            warning
            for warning in diff_warnings["warnings"]
            if isinstance(warning, str)
        ]
        evidence_used.append("diff_warnings.json")

    return {
        "session_status": _session_status(metadata),
        "request_available": request is not None and bool(request.strip()),
        "request": request,
        "plan_available": plan is not None and bool(plan.strip()),
        "plan": plan,
        "files_changed": _files_changed(file_changes, deterministic_review),
        "patch_available": diff_patch is not None and bool(diff_patch.strip()),
        "patch_preview": patch_preview,
        "patch_preview_truncated": patch_truncated,
        "change_summary": change_summary,
        "deterministic_review": deterministic_review,
        "warnings": warnings,
        "test_results_available": test_results is not None,
        "test_results": test_results,
        "test_output_tail": test_output_tail,
        "test_output_truncated": test_output_truncated,
        "evidence_used": evidence_used,
    }


def build_semantic_review_prompt(context: dict) -> str:
    prompt_template = get_prompt("semantic_patch_review")

    return prompt_template.render(
        review_context=json.dumps(context, indent=2, ensure_ascii=False),
    )


def parse_llm_review_response(text: str) -> dict:
    try:
        parsed = _extract_json_object(text)
    except ValueError as exc:
        return _parse_failed_review(str(exc))

    if not isinstance(parsed, dict):
        return _parse_failed_review("The LLM review response JSON must be an object.")

    return normalize_llm_review(parsed)


def normalize_llm_review(review: dict) -> dict:
    verdict = _allowed_value(review.get("verdict"), ALLOWED_VERDICTS, "needs_human_review")
    risk_level = _allowed_value(review.get("risk_level"), ALLOWED_RISK_LEVELS, "unknown")
    request_alignment = _allowed_value(
        review.get("request_alignment"),
        ALLOWED_REQUEST_ALIGNMENTS,
        "unknown",
    )
    confidence = review.get("confidence") if isinstance(review.get("confidence"), str) else "unknown"
    summary = review.get("summary") if isinstance(review.get("summary"), str) else ""
    risks = _string_list(review.get("risks"))
    suggested_checks = _string_list(review.get("suggested_checks"))
    evidence_used = _string_list(review.get("evidence_used"))
    notes = _string_list(review.get("notes"))

    if INFORMATIONAL_NOTE not in notes:
        notes.append(INFORMATIONAL_NOTE)

    return {
        "review_type": "llm",
        "status": "informational",
        "verdict": verdict,
        "confidence": confidence,
        "request_alignment": request_alignment,
        "risk_level": risk_level,
        "summary": summary,
        "risks": risks,
        "suggested_checks": suggested_checks,
        "evidence_used": evidence_used,
        "notes": notes,
    }


def render_llm_review_markdown(review: dict) -> str:
    risks = _markdown_list(_string_list(review.get("risks")))
    suggested_checks = _markdown_list(_string_list(review.get("suggested_checks")))
    evidence_used = _markdown_list(_string_list(review.get("evidence_used")))
    notes = _markdown_list(_string_list(review.get("notes")))

    return f"""# LLM Review

## Review Status

Informational only. This review does not prove semantic correctness.

## Verdict

{review.get("verdict", "needs_human_review")}

## Summary

{review.get("summary", "")}

## Request Alignment

{review.get("request_alignment", "unknown")}

## Risk Level

{review.get("risk_level", "unknown")}

## Risks

{risks}

## Suggested Checks

{suggested_checks}

## Evidence Used

{evidence_used}

## Notes

{notes}
""".strip() + "\n"


def write_llm_review_artifacts(
    session_dir: Path,
    review: dict,
    markdown: str,
    raw_text: str | None = None,
) -> None:
    (session_dir / "llm_review.md").write_text(markdown, encoding="utf-8")
    (session_dir / "llm_review.json").write_text(
        json.dumps(review, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if raw_text is not None:
        (session_dir / "llm_review_raw.txt").write_text(raw_text, encoding="utf-8")


def _parse_failed_review(error_message: str) -> dict:
    return {
        "review_type": "llm",
        "status": "parse_failed",
        "verdict": "needs_human_review",
        "confidence": "unknown",
        "request_alignment": "unknown",
        "risk_level": "unknown",
        "summary": "LLM review response could not be parsed.",
        "risks": [
            "Review output was not valid structured JSON.",
        ],
        "suggested_checks": [
            "Inspect llm_review_raw.txt and review the patch manually.",
        ],
        "evidence_used": [],
        "notes": [
            error_message,
            INFORMATIONAL_NOTE,
        ],
    }


def _extract_json_object(text: str) -> Any:
    stripped_text = text.strip()
    decoder = json.JSONDecoder()

    for index, char in enumerate(stripped_text):
        if char != "{":
            continue

        try:
            parsed_value, _end_index = decoder.raw_decode(stripped_text[index:])
        except json.JSONDecodeError:
            continue

        return parsed_value

    raise ValueError("The LLM review response does not contain a valid JSON object.")


def _read_optional_text(path: Path) -> str | None:
    if not path.exists():
        return None

    return path.read_text(encoding="utf-8")


def _read_optional_json(path: Path) -> Any:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _limit_lines(text: str, max_lines: int) -> tuple[str, bool]:
    lines = text.splitlines()

    if len(lines) <= max_lines:
        return text.rstrip("\n"), False

    return "\n".join(lines[:max_lines]), True


def _tail_lines(text: str, max_lines: int) -> tuple[str, bool]:
    lines = text.splitlines()

    if len(lines) <= max_lines:
        return text.rstrip("\n"), False

    return "\n".join(lines[-max_lines:]), True


def _session_status(metadata: Any) -> str | None:
    if isinstance(metadata, dict) and isinstance(metadata.get("status"), str):
        return metadata["status"]

    return None


def _files_changed(file_changes: Any, deterministic_review: Any) -> list[dict]:
    changes = None

    if isinstance(file_changes, dict) and isinstance(file_changes.get("changes"), list):
        changes = file_changes["changes"]
    elif (
        isinstance(deterministic_review, dict)
        and isinstance(deterministic_review.get("files_changed"), list)
    ):
        changes = deterministic_review["files_changed"]

    if not isinstance(changes, list):
        return []

    return [
        {
            "path": change.get("path"),
            "change_type": change.get("change_type"),
            "mode": change.get("mode"),
            "operation": change.get("operation"),
        }
        for change in changes
        if isinstance(change, dict)
    ]


def _allowed_value(value: Any, allowed_values: set[str], default: str) -> str:
    if isinstance(value, str) and value in allowed_values:
        return value

    return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def _markdown_list(items: list[str]) -> str:
    if not items:
        return "- None"

    return "\n".join(f"- {item}" for item in items)
