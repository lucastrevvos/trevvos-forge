import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from trevvos_forge.timeline import read_timeline
from trevvos_forge.verification_coverage import high_risk_warnings


RETRY_LIMIT = 3
REPAIR_LIMIT = 3


@dataclass(frozen=True)
class AgentState:
    session_id: str
    phase: str
    status: str
    reason: str | None
    next_action: str | None
    next_command: str | None
    confidence: str
    blockers: list[str]
    warnings: list[str]
    evidence: dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NextAction:
    action: str | None
    command: str | None
    reason: str | None
    confidence: str

    def to_dict(self) -> dict:
        return asdict(self)


def determine_agent_state(session_dir: Path) -> AgentState:
    metadata = _read_json(session_dir / "metadata.json")
    session_id = _session_id(metadata, session_dir)
    evidence = _collect_evidence(session_dir, metadata)
    warnings = _warnings(evidence)
    blockers = _blockers(evidence)

    if blockers:
        return _state(
            session_id=session_id,
            phase="blocked",
            status="blocked",
            reason=blockers[0],
            next_action=None,
            next_command=None,
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if isinstance(evidence["plan_error"], dict):
        error_type = evidence["plan_error"].get("error_type")
        phase = "plan_failed_json" if error_type == "invalid_plan_json" else "plan_failed_schema"
        reason = (
            "The previous plan failed because the model did not return valid JSON."
            if phase == "plan_failed_json"
            else "The previous plan failed because the model response did not match the plan schema."
        )
        return _state(
            session_id=session_id,
            phase=phase,
            status="needs_retry",
            reason=reason,
            next_action="retry_plan",
            next_command="trevvos plan --retry",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if not evidence["has_plan"]:
        return _state(
            session_id=session_id,
            phase="new",
            status="needs_action",
            reason="No plan.json was found for this session.",
            next_action="plan",
            next_command='trevvos plan "..."',
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if _verification_coverage_failed(evidence):
        return _state(
            session_id=session_id,
            phase="verification_coverage_failed",
            status="needs_retry",
            reason="Plan verification coverage failed.",
            next_action="retry_plan",
            next_command="trevvos plan --retry",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if _cli_regression_failed(evidence):
        return _state(
            session_id=session_id,
            phase="cli_regression_failed",
            status="needs_repair",
            reason="CLI regression check failed.",
            next_action="repair",
            next_command="trevvos repair",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if isinstance(evidence["file_changes_error"], dict):
        return _state(
            session_id=session_id,
            phase="diff_failed_schema",
            status="needs_retry",
            reason="The previous diff failed because file_changes schema was invalid.",
            next_action="retry_diff",
            next_command="trevvos diff --retry",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if isinstance(evidence["operation_error"], dict):
        return _state(
            session_id=session_id,
            phase="diff_failed_operation",
            status="needs_retry",
            reason="The previous diff failed because an operation could not be applied deterministically.",
            next_action="retry_diff",
            next_command="trevvos diff --retry",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    has_diff = evidence["has_diff"] and evidence["has_file_changes"]
    high_risk = high_risk_warnings(evidence.get("diff_warnings"))
    if has_diff and high_risk:
        return _state(
            session_id=session_id,
            phase="blocked_warning",
            status="blocked",
            reason="Work blocked by structural edit warning.",
            next_action=None,
            next_command="trevvos review --no-llm",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if _review_has_concerns(evidence):
        return _state(
            session_id=session_id,
            phase="review_has_concerns",
            status="needs_repair",
            reason="Review artifacts contain concerns.",
            next_action="repair" if has_diff else "retry_diff",
            next_command="trevvos repair" if has_diff else "trevvos diff --retry",
            confidence="high" if has_diff else "medium",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if not evidence["has_diff"]:
        return _state(
            session_id=session_id,
            phase="planned",
            status="needs_diff",
            reason="A plan exists, but no diff.patch was found.",
            next_action="diff",
            next_command="trevvos diff",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    sandbox_status = _test_status(evidence["sandbox_test_results"])
    working_tree_status = _test_status(evidence["working_tree_test_results"])

    if _commit_status(evidence["commit_result"]) == "committed":
        return _state(
            session_id=session_id,
            phase="complete",
            status="complete",
            reason="Commit has been created.",
            next_action=None,
            next_command=None,
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if evidence["has_apply_result"]:
        if working_tree_status == "not_run":
            return _state(
                session_id=session_id,
                phase="applied",
                status="needs_test",
                reason="Patch was applied, but working tree tests have not been run.",
                next_action="test_working_tree",
                next_command="trevvos test",
                confidence="high",
                blockers=blockers,
                warnings=warnings,
                evidence=evidence,
            )

        if working_tree_status in {"failed", "timed_out"}:
            return _state(
                session_id=session_id,
                phase="working_tree_test_failed",
                status="needs_repair",
                reason=f"Working tree tests {working_tree_status}.",
                next_action="repair",
                next_command="trevvos repair",
                confidence="high",
                blockers=blockers,
                warnings=warnings,
                evidence=evidence,
            )

        if working_tree_status == "passed":
            return _state(
                session_id=session_id,
                phase="ready_to_commit",
                status="ready",
                reason="Working tree tests passed and no commit has been created.",
                next_action="commit",
                next_command="trevvos commit",
                confidence="high",
                blockers=blockers,
                warnings=warnings,
                evidence=evidence,
            )

    if sandbox_status == "not_run":
        return _state(
            session_id=session_id,
            phase="sandbox_not_run",
            status="needs_test",
            reason="A diff exists, but sandbox tests have not been run.",
            next_action="test_sandbox",
            next_command="trevvos test --sandbox",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if sandbox_status in {"failed", "timed_out"}:
        return _state(
            session_id=session_id,
            phase="sandbox_failed",
            status="needs_repair",
            reason=f"Sandbox tests {sandbox_status}.",
            next_action="repair",
            next_command="trevvos repair",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if sandbox_status == "passed" and not _has_review(evidence):
        return _state(
            session_id=session_id,
            phase="sandbox_passed",
            status="needs_review",
            reason="Sandbox tests passed, but review has not been run.",
            next_action="review",
            next_command="trevvos review",
            confidence="high",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    if not evidence["has_apply_result"]:
        return _state(
            session_id=session_id,
            phase="ready_to_apply",
            status="ready",
            reason="Diff is validated, sandbox passed, and review has no blocking concerns.",
            next_action="apply",
            next_command="trevvos apply",
            confidence="medium",
            blockers=blockers,
            warnings=warnings,
            evidence=evidence,
        )

    return _state(
        session_id=session_id,
        phase="unknown",
        status="unknown",
        reason="Session artifacts did not match a known agent state.",
        next_action=None,
        next_command=None,
        confidence="low",
        blockers=blockers,
        warnings=warnings,
        evidence=evidence,
    )


def determine_next_action(agent_state: AgentState) -> NextAction:
    return NextAction(
        action=agent_state.next_action,
        command=agent_state.next_command,
        reason=agent_state.reason,
        confidence=agent_state.confidence,
    )


def _collect_evidence(session_dir: Path, metadata: Any) -> dict:
    sandbox = _read_json(session_dir / "sandbox_test_results.json")
    working_tree = _read_json(session_dir / "working_tree_test_results.json")
    legacy_test_results = _read_json(session_dir / "test_results.json")

    if not isinstance(sandbox, dict) and _test_mode(legacy_test_results) == "sandbox":
        sandbox = legacy_test_results
    if not isinstance(working_tree, dict) and _test_mode(legacy_test_results) == "working_tree":
        working_tree = legacy_test_results

    retry_metadata = _read_json(session_dir / "retry_metadata.json")
    repair_metadata = _read_json(session_dir / "repair_metadata.json")

    return {
        "metadata_status": metadata.get("status") if isinstance(metadata, dict) else None,
        "plan_error": _read_json(session_dir / "plan_error.json"),
        "has_plan": (session_dir / "plan.json").exists(),
        "has_diff": (session_dir / "diff.patch").exists(),
        "has_file_changes": _valid_file_changes(session_dir / "file_changes.json"),
        "has_apply_result": _has_apply_result(session_dir / "apply_result.json", metadata),
        "file_changes_error": _read_json(session_dir / "file_changes_error.json"),
        "operation_error": _read_json(session_dir / "operation_error.json"),
        "plan_constraints_check": _read_json(session_dir / "plan_constraints_check.json"),
        "verification_coverage": _read_json(session_dir / "verification_coverage.json"),
        "cli_regression_check": _read_json(session_dir / "cli_regression_check.json"),
        "sandbox_test_results": sandbox,
        "working_tree_test_results": working_tree,
        "semantic_review": _read_json(session_dir / "semantic_review.json"),
        "llm_review": _read_json(session_dir / "llm_review.json"),
        "retry_metadata": retry_metadata,
        "plan_retry_metadata": _read_json(session_dir / "plan_retry_metadata.json"),
        "repair_metadata": repair_metadata,
        "retry_count": _count_value(retry_metadata, "retry_count"),
        "repair_count": _count_value(repair_metadata, "repair_count"),
        "apply_result": _read_json(session_dir / "apply_result.json"),
        "commit_result": _read_json(session_dir / "commit_result.json"),
        "timeline": read_timeline(session_dir),
        "diff_warnings": _read_json(session_dir / "diff_warnings.json"),
    }


def _state(
    *,
    session_id: str,
    phase: str,
    status: str,
    reason: str | None,
    next_action: str | None,
    next_command: str | None,
    confidence: str,
    blockers: list[str],
    warnings: list[str],
    evidence: dict,
) -> AgentState:
    return AgentState(
        session_id=session_id,
        phase=phase,
        status=status,
        reason=reason,
        next_action=next_action,
        next_command=next_command,
        confidence=confidence,
        blockers=blockers,
        warnings=warnings,
        evidence=_evidence_summary(evidence),
    )


def _evidence_summary(evidence: dict) -> dict:
    return {
        "has_plan": evidence.get("has_plan"),
        "has_plan_error": isinstance(evidence.get("plan_error"), dict),
        "verification_coverage_status": _verification_coverage_status(evidence.get("verification_coverage")),
        "cli_regression_status": _cli_regression_status(evidence.get("cli_regression_check")),
        "has_diff": evidence.get("has_diff"),
        "has_file_changes": evidence.get("has_file_changes"),
        "sandbox_status": _test_status(evidence.get("sandbox_test_results")),
        "working_tree_status": _test_status(evidence.get("working_tree_test_results")),
        "has_semantic_review": isinstance(evidence.get("semantic_review"), dict),
        "has_llm_review": isinstance(evidence.get("llm_review"), dict),
        "has_apply_result": evidence.get("has_apply_result"),
        "commit_status": _commit_status(evidence.get("commit_result")),
        "retry_count": evidence.get("retry_count"),
        "repair_count": evidence.get("repair_count"),
    }


def _blockers(evidence: dict) -> list[str]:
    blockers: list[str] = []
    constraints = evidence.get("plan_constraints_check")
    if isinstance(constraints, dict) and constraints.get("status") == "failed":
        blockers.append("Plan constraints check failed.")

    if any(event.get("event") == "unsafe_command_blocked" for event in _event_dicts(evidence.get("timeline"))):
        blockers.append("Unsafe command was blocked.")

    if isinstance(evidence.get("retry_count"), int) and evidence["retry_count"] >= RETRY_LIMIT:
        blockers.append("Retry limit reached.")

    if isinstance(evidence.get("repair_count"), int) and evidence["repair_count"] >= REPAIR_LIMIT:
        blockers.append("Repair limit reached.")

    return blockers


def _warnings(evidence: dict) -> list[str]:
    diff_warnings = evidence.get("diff_warnings")
    if not isinstance(diff_warnings, dict) or not isinstance(diff_warnings.get("warnings"), list):
        return []
    return [warning for warning in diff_warnings["warnings"] if isinstance(warning, str)]


def _verification_coverage_failed(evidence: dict) -> bool:
    return _verification_coverage_status(evidence.get("verification_coverage")) == "failed"


def _cli_regression_failed(evidence: dict) -> bool:
    return _cli_regression_status(evidence.get("cli_regression_check")) == "failed"


def _verification_coverage_status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "not_run"
    status = payload.get("status")
    return status if status in {"passed", "warning", "failed"} else "unknown"


def _cli_regression_status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "not_applicable"
    status = payload.get("status")
    return status if status in {"passed", "warning", "failed", "not_applicable"} else "unknown"


def _review_has_concerns(evidence: dict) -> bool:
    semantic = evidence.get("semantic_review")
    if isinstance(semantic, dict):
        concerns = semantic.get("concerns")
        if isinstance(concerns, list) and any(isinstance(item, str) and item.strip() for item in concerns):
            return True
        if semantic.get("verdict") in {"has_concerns", "blocked"}:
            return True

    llm = evidence.get("llm_review")
    if isinstance(llm, dict) and llm.get("verdict") in {"has_concerns", "blocked"}:
        return True

    return False


def _has_review(evidence: dict) -> bool:
    return isinstance(evidence.get("semantic_review"), dict) or isinstance(evidence.get("llm_review"), dict)


def _test_status(test_results: Any) -> str:
    if not isinstance(test_results, dict):
        return "not_run"
    status = test_results.get("status")
    return status if status in {"passed", "failed", "timed_out"} else "unknown"


def _test_mode(test_results: Any) -> str | None:
    if not isinstance(test_results, dict):
        return None
    mode = test_results.get("mode", "working_tree")
    return mode if isinstance(mode, str) else None


def _commit_status(commit_result: Any) -> str:
    if not isinstance(commit_result, dict):
        return "not_run"
    status = commit_result.get("status")
    return status if isinstance(status, str) else "not_run"


def _has_apply_result(path: Path, metadata: Any) -> bool:
    apply_result = _read_json(path)
    if isinstance(apply_result, dict) and apply_result.get("applied") is True:
        return True
    return isinstance(metadata, dict) and metadata.get("status") == "applied"


def _valid_file_changes(path: Path) -> bool:
    payload = _read_json(path)
    return isinstance(payload, dict) and isinstance(payload.get("changes"), list)


def _count_value(payload: Any, key: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return value if isinstance(value, int) else None


def _event_dicts(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _session_id(metadata: Any, session_dir: Path) -> str:
    if isinstance(metadata, dict) and isinstance(metadata.get("id"), str):
        return metadata["id"]
    return session_dir.name


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
