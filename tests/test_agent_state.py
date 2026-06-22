import json
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from trevvos_forge.agent_state import determine_agent_state, determine_next_action
from trevvos_forge.cli import app
from trevvos_forge.sessions import create_session, write_patch_file, write_session_json, write_session_text
from trevvos_forge.status_workflow import build_session_status, render_status_text


class AgentStateTests(unittest.TestCase):
    def test_empty_session_is_new(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_metadata(session_dir)

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "new")
            self.assertEqual(state.next_command, 'trevvos plan "..."')

    def test_file_changes_error_recommends_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True)
            _write_json(
                session_dir / "file_changes_error.json",
                {"error_type": "invalid_file_changes_schema"},
            )

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "diff_failed_schema")
            self.assertEqual(state.next_command, "trevvos diff --retry")

    def test_plan_error_recommends_plan_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=False)
            _write_json(
                session_dir / "plan_error.json",
                {"error_type": "invalid_plan_json"},
            )

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "plan_failed_json")
            self.assertEqual(state.next_action, "retry_plan")
            self.assertEqual(state.next_command, "trevvos plan --retry")

    def test_operation_error_recommends_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True)
            _write_json(session_dir / "operation_error.json", {"error_type": "target_not_found"})

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "diff_failed_operation")
            self.assertEqual(state.next_command, "trevvos diff --retry")

    def test_verification_coverage_failed_recommends_plan_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True)
            _write_json(session_dir / "verification_coverage.json", {"status": "failed"})

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "verification_coverage_failed")
            self.assertEqual(state.next_command, "trevvos plan --retry")

    def test_cli_regression_failed_recommends_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True)
            _write_json(session_dir / "cli_regression_check.json", {"status": "failed"})

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "cli_regression_failed")
            self.assertEqual(state.next_command, "trevvos repair")

    def test_plan_without_diff_recommends_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True)

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "planned")
            self.assertEqual(state.next_command, "trevvos diff")

    def test_diff_without_sandbox_recommends_sandbox_test(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True)

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "sandbox_not_run")
            self.assertEqual(state.next_command, "trevvos test --sandbox")

    def test_sandbox_failed_recommends_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True)
            _write_test_result(session_dir, "sandbox", "failed")

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "sandbox_failed")
            self.assertEqual(state.next_command, "trevvos repair")

    def test_sandbox_passed_without_review_recommends_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True)
            _write_test_result(session_dir, "sandbox", "passed")

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "sandbox_passed")
            self.assertEqual(state.next_command, "trevvos review")

    def test_review_concerns_recommend_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True)
            _write_test_result(session_dir, "sandbox", "passed")
            _write_json(session_dir / "semantic_review.json", {"concerns": ["Behavior is wrong."]})

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "review_has_concerns")
            self.assertEqual(state.next_command, "trevvos repair")

    def test_sandbox_passed_review_ok_recommends_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True)
            _write_test_result(session_dir, "sandbox", "passed")
            _write_json(session_dir / "semantic_review.json", {"concerns": [], "warnings": []})

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "ready_to_apply")
            self.assertEqual(state.next_command, "trevvos apply")

    def test_high_risk_diff_warning_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True)
            _write_json(
                session_dir / "diff_warnings.json",
                {"warnings": ["Small file structural edit risk: main.py received local append operations."]},
            )

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "blocked_warning")
            self.assertEqual(state.next_command, "trevvos review --no-llm")

    def test_apply_without_working_tree_test_recommends_test(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True, applied=True)

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "applied")
            self.assertEqual(state.next_command, "trevvos test")

    def test_working_tree_failed_recommends_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True, applied=True)
            _write_test_result(session_dir, "working_tree", "failed")

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "working_tree_test_failed")
            self.assertEqual(state.next_command, "trevvos repair")

    def test_working_tree_passed_recommends_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True, applied=True)
            _write_test_result(session_dir, "working_tree", "passed")

            state = determine_agent_state(session_dir)

            self.assertEqual(state.phase, "ready_to_commit")
            self.assertEqual(state.next_command, "trevvos commit")

    def test_commit_created_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True, applied=True)
            _write_test_result(session_dir, "working_tree", "passed")
            _write_json(session_dir / "commit_result.json", {"status": "committed", "commit_hash": "abc123"})

            state = determine_agent_state(session_dir)
            action = determine_next_action(state)

            self.assertEqual(state.phase, "complete")
            self.assertIsNone(state.next_command)
            self.assertIsNone(action.command)

    def test_status_includes_agent_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = _session(Path(temporary_directory), plan=True, diff=True)
            status = build_session_status(session_dir)
            rendered = render_status_text(status)

            self.assertEqual(status["agent_state"]["phase"], "sandbox_not_run")
            self.assertIn("Agent state:", rendered)
            self.assertIn("Phase: sandbox_not_run", rendered)
            self.assertIn("Next: trevvos test --sandbox", rendered)

    def test_trevvos_next_outputs_recommendation(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update CLI", command="plan")
            write_session_json(session, "plan.json", {"summary": "Plan."})
            write_session_text(session, "plan.md", "Plan.")
            write_session_json(
                session,
                "file_changes_error.json",
                {"error_type": "invalid_file_changes_schema"},
            )

            result = runner.invoke(app, ["next", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("trevvos diff --retry", result.output)
            self.assertIn("file_changes schema was invalid", result.output)


def _session(root: Path, *, plan: bool = False, diff: bool = False, applied: bool = False) -> Path:
    session_dir = root / "session"
    session_dir.mkdir()
    _write_metadata(session_dir, status="applied" if applied else "diff_validated" if diff else "planned")
    if plan:
        _write_json(session_dir / "plan.json", {"summary": "Plan."})
    if diff:
        write_patch_file(session_dir / "diff.patch", "diff --git a/main.py b/main.py\n")
        _write_json(
            session_dir / "file_changes.json",
            {"changes": [{"path": "main.py", "change_type": "modified", "mode": "full_file_rewrite"}]},
        )
    if applied:
        _write_json(session_dir / "apply_result.json", {"applied": True})
    return session_dir


def _write_metadata(session_dir: Path, status: str = "created") -> None:
    _write_json(
        session_dir / "metadata.json",
        {
            "id": "test-session",
            "created_at": "2026-06-22T00:00:00+00:00",
            "status": status,
            "command": "test",
            "workspace_root": str(session_dir.parent),
        },
    )


def _write_test_result(session_dir: Path, mode: str, status: str) -> None:
    name = "sandbox_test_results.json" if mode == "sandbox" else "working_tree_test_results.json"
    _write_json(session_dir / name, {"mode": mode, "status": status})


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
