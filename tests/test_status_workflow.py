import json
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.status_workflow import (
    build_session_status,
    render_status_text,
    write_session_status,
)
from trevvos_forge.sessions import write_patch_file


class StatusWorkflowTests(unittest.TestCase):
    def test_session_without_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_metadata(session_dir)
            (session_dir / "plan.md").write_text("Plan.", encoding="utf-8")

            status = build_session_status(session_dir)

            self.assertEqual(status["checks"]["diff"], "missing")
            self.assertEqual(status["overall_status"], "planning")
            self.assertEqual(status["next_recommended_command"], "trevvos diff")

    def test_diff_validated_without_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir)

            status = build_session_status(session_dir)

            self.assertEqual(status["checks"]["diff"], "done")
            self.assertEqual(status["checks"]["safety_validation"], "passed")
            self.assertEqual(status["checks"]["git_apply_check"], "passed")
            self.assertEqual(status["checks"]["sandbox_test"], "not_run")
            self.assertEqual(status["next_recommended_command"], "trevvos test --sandbox")

    def test_sandbox_passed_and_apply_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir)
            _write_test_results(session_dir, mode="sandbox", status="passed")

            status = build_session_status(session_dir)

            self.assertEqual(status["checks"]["sandbox_test"], "passed")
            self.assertEqual(status["next_recommended_command"], "trevvos review")

    def test_sandbox_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir)
            _write_test_results(session_dir, mode="sandbox", status="failed")

            status = build_session_status(session_dir)

            self.assertEqual(status["overall_status"], "sandbox_test_failed")
            self.assertEqual(status["next_recommended_command"], "Review test_output.log")

    def test_working_tree_test_passed_and_commit_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir, metadata_status="applied")
            _write_test_results(session_dir, mode="working_tree", status="passed")

            status = build_session_status(session_dir)

            self.assertEqual(status["checks"]["apply"], "applied")
            self.assertEqual(status["checks"]["working_tree_test"], "passed")
            self.assertEqual(status["next_recommended_command"], "trevvos commit")

    def test_status_reads_sandbox_and_working_tree_results_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir, metadata_status="applied")
            _write_test_results(session_dir, mode="sandbox", status="passed", specific=True)
            _write_test_results(session_dir, mode="working_tree", status="passed", specific=True)

            status = build_session_status(session_dir)
            rendered = render_status_text(status, verbose=True)

            self.assertEqual(status["checks"]["sandbox_test"], "passed")
            self.assertEqual(status["checks"]["working_tree_test"], "passed")
            self.assertIn("Sandbox test status: passed", rendered)
            self.assertIn("Working tree test status: passed", rendered)

    def test_status_legacy_sandbox_alias_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir)
            _write_test_results(session_dir, mode="sandbox", status="passed")

            status = build_session_status(session_dir)

            self.assertEqual(status["checks"]["sandbox_test"], "passed")
            self.assertEqual(status["checks"]["working_tree_test"], "not_run")

    def test_status_legacy_working_tree_alias_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir, metadata_status="applied")
            _write_test_results(session_dir, mode="working_tree", status="passed")

            status = build_session_status(session_dir)

            self.assertEqual(status["checks"]["sandbox_test"], "not_run")
            self.assertEqual(status["checks"]["working_tree_test"], "passed")

    def test_commit_committed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir, metadata_status="applied")
            _write_test_results(session_dir, mode="working_tree", status="passed")
            (session_dir / "commit_result.json").write_text(
                json.dumps(
                    {
                        "status": "committed",
                        "commit_hash": "abc123",
                        "message_subject": "Update docs",
                    }
                ),
                encoding="utf-8",
            )

            status = build_session_status(session_dir)

            self.assertEqual(status["checks"]["commit"], "committed")
            self.assertEqual(status["overall_status"], "complete")
            self.assertIsNone(status["next_recommended_command"])
            self.assertEqual(status["details"]["commit"]["hash"], "abc123")

    def test_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir)
            (session_dir / "diff_warnings.json").write_text(
                json.dumps({"warnings": ["Review patch manually."]}),
                encoding="utf-8",
            )

            status = build_session_status(session_dir)
            rendered = render_status_text(status)

            self.assertEqual(status["warnings"], ["Review patch manually."])
            self.assertIn("Review patch manually.", rendered)

    def test_review_parse_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir)
            (session_dir / "llm_review.json").write_text(
                json.dumps(
                    {
                        "status": "parse_failed",
                        "verdict": "needs_human_review",
                        "risk_level": "unknown",
                    }
                ),
                encoding="utf-8",
            )

            status = build_session_status(session_dir)

            self.assertEqual(status["checks"]["review"], "parse_failed")
            self.assertEqual(status["overall_status"], "needs_attention")

    def test_render_text_and_write_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_validated_diff(session_dir)

            status = build_session_status(session_dir)
            rendered = render_status_text(status, verbose=True)
            write_session_status(session_dir, status)

            self.assertIn("Session:", rendered)
            self.assertIn("Checklist:", rendered)
            self.assertIn("OK", rendered)
            self.assertIn("Warnings:", rendered)
            self.assertIn("Next:", rendered)
            self.assertTrue((session_dir / "session_status.json").exists())
            json.dumps(status)


def _write_metadata(session_dir: Path, status: str = "planned") -> None:
    (session_dir / "metadata.json").write_text(
        json.dumps(
            {
                "id": "test-session",
                "created_at": "2026-06-21T00:00:00+00:00",
                "status": status,
                "command": "plan",
                "workspace_root": str(session_dir.parent),
            }
        ),
        encoding="utf-8",
    )


def _write_validated_diff(session_dir: Path, metadata_status: str = "diff_validated") -> None:
    _write_metadata(session_dir, status=metadata_status)
    (session_dir / "plan.md").write_text("Plan.", encoding="utf-8")
    write_patch_file(session_dir / "diff.patch", "diff --git a/README.md b/README.md\n")
    (session_dir / "change_summary.md").write_text("# Change Summary\n", encoding="utf-8")
    (session_dir / "diff_validation.json").write_text(
        json.dumps({"is_valid": True, "changes": [], "warnings": []}),
        encoding="utf-8",
    )
    (session_dir / "diff_check.json").write_text(
        json.dumps({"git_apply_check": "passed"}),
        encoding="utf-8",
    )


def _write_test_results(session_dir: Path, *, mode: str, status: str, specific: bool = False) -> None:
    file_name = (
        "sandbox_test_results.json"
        if specific and mode == "sandbox"
        else "working_tree_test_results.json"
        if specific
        else "test_results.json"
    )
    (session_dir / file_name).write_text(
        json.dumps(
            {
                "mode": mode,
                "status": status,
                "summary": {
                    "total": 1,
                    "passed": 1 if status == "passed" else 0,
                    "failed": 1 if status == "failed" else 0,
                    "timed_out": 1 if status == "timed_out" else 0,
                },
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
