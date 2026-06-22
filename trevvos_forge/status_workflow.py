import json
from pathlib import Path
from typing import Any


CHECK_LABELS = {
    "plan": "Plan generated",
    "diff": "Diff generated",
    "safety_validation": "Safety validation passed",
    "git_apply_check": "git apply --check passed",
    "sandbox_test": "Sandbox tests passed",
    "review": "Review generated",
    "apply": "Patch applied",
    "working_tree_test": "Working tree tests passed",
    "commit": "Commit created",
}


def build_session_status(session_dir: Path, repo_root: Path | None = None) -> dict:
    metadata = _read_json(session_dir / "metadata.json")
    test_results = _read_json(session_dir / "test_results.json")
    llm_review = _read_json(session_dir / "llm_review.json")
    deterministic_review = _read_json(session_dir / "semantic_review.json")
    commit_result = _read_json(session_dir / "commit_result.json")
    diff_warnings = _read_json(session_dir / "diff_warnings.json")
    apply_result = _read_json(session_dir / "apply_result.json")
    diff_check = _read_json(session_dir / "diff_check.json")

    checks = {
        "plan": _plan_status(session_dir),
        "diff": "done" if (session_dir / "diff.patch").exists() else "missing",
        "safety_validation": _safety_validation_status(session_dir, metadata),
        "git_apply_check": _git_apply_check_status(session_dir, metadata, diff_check),
        "sandbox_test": _sandbox_test_status(test_results),
        "review": _review_status(llm_review, deterministic_review),
        "apply": _apply_status(session_dir, metadata, apply_result),
        "working_tree_test": _working_tree_test_status(test_results),
        "commit": _commit_status(commit_result),
    }
    warnings = _warnings(diff_warnings)
    details = {
        "review": _review_details(llm_review, deterministic_review),
        "commit": _commit_details(commit_result),
        "test": _test_details(test_results),
        "artifacts": _artifact_details(session_dir),
    }
    artifacts = _existing_artifacts(session_dir)
    status = {
        "session_id": _session_id(metadata, session_dir),
        "overall_status": "unknown",
        "next_recommended_command": None,
        "checks": checks,
        "warnings": warnings,
        "artifacts": artifacts,
        "details": details,
    }
    status["overall_status"] = determine_overall_status(status)
    status["next_recommended_command"] = determine_next_command(status)

    return status


def determine_overall_status(status: dict) -> str:
    checks = status.get("checks", {})
    warnings = status.get("warnings", [])
    review = status.get("details", {}).get("review", {})

    if review.get("verdict") in {"has_concerns", "blocked"} or review.get("status") == "parse_failed":
        return "needs_attention"

    if warnings:
        return "needs_attention"

    if checks.get("diff") == "missing":
        return "planning"

    if checks.get("safety_validation") != "passed" or checks.get("git_apply_check") != "passed":
        return "needs_attention"

    if checks.get("sandbox_test") in {"failed", "timed_out"}:
        return "sandbox_test_failed"

    if checks.get("apply") not in {"applied", "likely_applied"}:
        if checks.get("sandbox_test") == "passed":
            return "ready_to_apply"

        return "diff_ready"

    if checks.get("working_tree_test") in {"failed", "timed_out"}:
        return "tests_failed"

    if checks.get("working_tree_test") != "passed":
        return "applied"

    if checks.get("commit") == "committed":
        return "complete"

    return "ready_to_commit"


def determine_next_command(status: dict) -> str | None:
    checks = status.get("checks", {})
    overall_status = status.get("overall_status")

    if checks.get("diff") == "missing":
        return "trevvos diff"

    if checks.get("safety_validation") != "passed" or checks.get("git_apply_check") != "passed":
        return "Review diff validation artifacts"

    if checks.get("sandbox_test") in {"failed", "timed_out"}:
        return "Review test_output.log"

    if checks.get("apply") not in {"applied", "likely_applied"} and checks.get("sandbox_test") == "not_run":
        return "trevvos test --sandbox"

    if checks.get("apply") not in {"applied", "likely_applied"} and checks.get("review") == "not_run":
        return "trevvos review"

    if checks.get("apply") not in {"applied", "likely_applied"}:
        return "trevvos apply"

    if checks.get("working_tree_test") in {"failed", "timed_out"}:
        return "Review test_output.log"

    if checks.get("working_tree_test") == "not_run":
        return "trevvos test"

    if checks.get("commit") == "not_run":
        return "trevvos commit"

    if overall_status == "complete":
        return None

    return None


def render_status_text(status: dict, verbose: bool = False) -> str:
    lines = [
        f"Session: {status.get('session_id')}",
        "",
        "Checklist:",
    ]
    checks = status.get("checks", {})

    for check_name, label in CHECK_LABELS.items():
        lines.append(f"{_check_marker(check_name, checks.get(check_name))} {label}: {checks.get(check_name)}")

    lines.extend(["", "Warnings:"])
    warnings = status.get("warnings", [])

    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")

    lines.extend(["", "Artifacts:"])
    artifacts = status.get("artifacts", [])

    if artifacts:
        lines.extend(f"- {artifact}" for artifact in artifacts)
    else:
        lines.append("- None")

    if verbose:
        lines.extend(_verbose_lines(status))

    lines.extend(["", "Next:"])
    next_command = status.get("next_recommended_command")
    lines.append(next_command if next_command else "Session complete.")

    return "\n".join(lines) + "\n"


def write_session_status(session_dir: Path, status: dict) -> None:
    (session_dir / "session_status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _plan_status(session_dir: Path) -> str:
    if (session_dir / "plan.md").exists() or (session_dir / "plan.json").exists():
        return "done"

    return "missing"


def _safety_validation_status(session_dir: Path, metadata: Any) -> str:
    if (session_dir / "diff_validation_error.txt").exists():
        return "failed"

    if (session_dir / "diff_validation.json").exists():
        return "passed"

    if _metadata_status(metadata) == "diff_validation_failed":
        return "failed"

    return "missing"


def _git_apply_check_status(session_dir: Path, metadata: Any, diff_check: Any) -> str:
    if (session_dir / "diff_check_error.txt").exists():
        return "failed"

    if isinstance(diff_check, dict) and diff_check.get("git_apply_check") == "passed":
        return "passed"

    if _metadata_status(metadata) == "diff_check_failed":
        return "failed"

    return "missing"


def _sandbox_test_status(test_results: Any) -> str:
    if not isinstance(test_results, dict):
        return "not_run"

    if test_results.get("mode") != "sandbox":
        return "not_run"

    return _allowed_test_status(test_results.get("status"))


def _working_tree_test_status(test_results: Any) -> str:
    if not isinstance(test_results, dict):
        return "not_run"

    if test_results.get("mode", "working_tree") != "working_tree":
        return "not_run"

    return _allowed_test_status(test_results.get("status"))


def _review_status(llm_review: Any, deterministic_review: Any) -> str:
    if isinstance(llm_review, dict):
        if llm_review.get("status") == "parse_failed":
            return "parse_failed"

        return "llm_reviewed"

    if isinstance(deterministic_review, dict):
        return "deterministic_only"

    return "not_run"


def _apply_status(session_dir: Path, metadata: Any, apply_result: Any) -> str:
    if isinstance(apply_result, dict) and apply_result.get("applied") is True:
        return "applied"

    if _metadata_status(metadata) == "applied":
        return "applied"

    if (session_dir / "apply_error.txt").exists():
        return "not_applied"

    return "unknown"


def _commit_status(commit_result: Any) -> str:
    if not isinstance(commit_result, dict):
        return "not_run"

    status = commit_result.get("status")

    if status in {"committed", "dry_run", "cancelled", "failed"}:
        return status

    return "not_run"


def _warnings(diff_warnings: Any) -> list[str]:
    if not isinstance(diff_warnings, dict) or not isinstance(diff_warnings.get("warnings"), list):
        return []

    return [warning for warning in diff_warnings["warnings"] if isinstance(warning, str)]


def _review_details(llm_review: Any, deterministic_review: Any) -> dict:
    source = llm_review if isinstance(llm_review, dict) else deterministic_review

    if not isinstance(source, dict):
        return {}

    return {
        "status": source.get("status"),
        "verdict": source.get("verdict"),
        "risk_level": source.get("risk_level"),
        "request_alignment": source.get("request_alignment"),
    }


def _commit_details(commit_result: Any) -> dict:
    if not isinstance(commit_result, dict):
        return {}

    return {
        "hash": commit_result.get("commit_hash"),
        "message_subject": commit_result.get("message_subject"),
    }


def _test_details(test_results: Any) -> dict:
    if not isinstance(test_results, dict):
        return {}

    return {
        "mode": test_results.get("mode", "working_tree"),
        "status": test_results.get("status"),
        "summary": test_results.get("summary"),
        "command_sources": test_results.get("command_sources"),
    }


def _artifact_details(session_dir: Path) -> dict:
    return {
        artifact: str(session_dir / artifact)
        for artifact in _existing_artifacts(session_dir)
    }


def _existing_artifacts(session_dir: Path) -> list[str]:
    artifact_names = [
        "plan.md",
        "diff.patch",
        "diff_warnings.json",
        "plan_constraints_check.json",
        "diff_validation.json",
        "diff_check.json",
        "change_summary.md",
        "semantic_review.json",
        "test_results.json",
        "test_output.log",
        "llm_review.json",
        "llm_review.md",
        "commit_message.txt",
        "commit_plan.json",
        "commit_result.json",
    ]

    return [artifact for artifact in artifact_names if (session_dir / artifact).exists()]


def _verbose_lines(status: dict) -> list[str]:
    details = status.get("details", {})
    lines = ["", "Details:"]
    review = details.get("review", {})
    commit = details.get("commit", {})
    test = details.get("test", {})
    artifacts = details.get("artifacts", {})

    if review:
        lines.append(f"- Review verdict: {review.get('verdict', 'unknown')}")
        lines.append(f"- Review risk: {review.get('risk_level', 'unknown')}")
        lines.append(f"- Request alignment: {review.get('request_alignment', 'unknown')}")

    if test:
        lines.append(f"- Test mode: {test.get('mode', 'unknown')}")
        lines.append(f"- Test status: {test.get('status', 'unknown')}")
        command_sources = test.get("command_sources")

        if isinstance(command_sources, dict):
            sources = []

            if command_sources.get("configured"):
                sources.append("configured")

            if command_sources.get("plan"):
                sources.append("plan")

            if sources:
                lines.append(f"- Verification commands: {' + '.join(sources)}")

    if commit:
        lines.append(f"- Commit hash: {commit.get('hash') or 'not available'}")
        lines.append(f"- Commit subject: {commit.get('message_subject') or 'not available'}")

    if artifacts:
        lines.append("- Artifact paths:")
        lines.extend(f"  - {name}: {path}" for name, path in artifacts.items())

    return lines


def _check_marker(check_name: str, status: str | None) -> str:
    if check_name == "review":
        return "OK" if status in {"llm_reviewed", "deterministic_only"} else "--"

    if status in {"done", "passed", "applied", "likely_applied", "committed"}:
        return "OK"

    return "--"


def _allowed_test_status(value: Any) -> str:
    if value in {"passed", "failed", "timed_out"}:
        return str(value)

    return "unknown"


def _session_id(metadata: Any, session_dir: Path) -> str:
    if isinstance(metadata, dict) and isinstance(metadata.get("id"), str):
        return metadata["id"]

    return session_dir.name


def _metadata_status(metadata: Any) -> str | None:
    if isinstance(metadata, dict) and isinstance(metadata.get("status"), str):
        return metadata["status"]

    return None


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
