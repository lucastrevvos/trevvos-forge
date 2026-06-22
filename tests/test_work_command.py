import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.sessions import create_session, update_session_status, write_patch_file, write_session_json
from trevvos_forge.timeline import read_timeline


class WorkCommandTests(unittest.TestCase):
    def test_happy_path_reaches_ready_to_apply_without_auto_apply(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _QueueProvider(
                [
                    _plan_response(files_to_create=["main.py"]),
                    _create_main_response("print('ok')\n"),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Create CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Work reached ready_to_apply", result.output)
            self.assertFalse((root / "main.py").exists())

            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "work_metadata.json")
            self.assertEqual(metadata["status"], "ready_to_apply")
            self.assertEqual(metadata["final_phase"], "ready_to_apply")
            self.assertEqual(metadata["next_command"], "trevvos apply")
            self.assertTrue((session_dir / "work_summary.md").exists())

    def test_schema_error_then_retry_success(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _QueueProvider(
                [
                    _plan_response(files_to_create=["main.py"]),
                    '{"foo": []}',
                    _create_main_response("print('ok')\n"),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Create CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "work_metadata.json")

            self.assertEqual(metadata["retries_used"], 1)
            self.assertEqual(metadata["status"], "ready_to_apply")
            self.assertIn("diff_retry", [step["step"] for step in metadata["steps"]])

    def test_operation_error_then_retry_success(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('old')\n", encoding="utf-8")
            provider = _QueueProvider(
                [
                    _plan_response(files_to_modify=["main.py"]),
                    _missing_target_response(),
                    _rewrite_main_response("print('ok')\n"),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Update CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "work_metadata.json")

            self.assertEqual(metadata["retries_used"], 1)
            self.assertEqual(metadata["status"], "ready_to_apply")

    def test_plan_error_then_plan_retry_success(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _QueueProvider(
                [
                    "Aqui esta o plano:\n- faca X",
                    _plan_response(files_to_create=["main.py"]),
                    _create_main_response("print('ok')\n"),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Create CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "work_metadata.json")
            events = [event["event"] for event in read_timeline(session_dir)]

            self.assertEqual(metadata["status"], "ready_to_apply")
            self.assertEqual(metadata["plan_retries_used"], 1)
            self.assertIn("plan_retry", [step["step"] for step in metadata["steps"]])
            self.assertIn("plan_failed", events)
            self.assertIn("plan_retry_completed", events)

    def test_max_plan_retries_reached_does_not_call_diff(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _QueueProvider(
                [
                    "invalid plan",
                    "still invalid",
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["work", "Create CLI", "--path", str(root), "--max-plan-retries", "1"],
                )

            self.assertEqual(result.exit_code, 1)
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "work_metadata.json")

            self.assertEqual(metadata["status"], "blocked")
            self.assertEqual(metadata["reason"], "max_plan_retries_reached")
            self.assertEqual(metadata["plan_retries_used"], 1)
            self.assertFalse((session_dir / "diff.patch").exists())
            self.assertNotIn("diff", [step["step"] for step in metadata["steps"]])

    def test_work_blocks_when_verification_coverage_failed(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _QueueProvider(
                [
                    _plan_response_with_uncovered_cli_command(),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["work", "Add sqrt CLI", "--path", str(root), "--max-plan-retries", "0"],
                )

            self.assertEqual(result.exit_code, 1)
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "work_metadata.json")
            coverage = _read_json(session_dir / "verification_coverage.json")

            self.assertEqual(metadata["status"], "blocked")
            self.assertEqual(metadata["reason"], "verification_coverage_failed")
            self.assertEqual(coverage["status"], "failed")
            self.assertFalse((session_dir / "diff.patch").exists())

    def test_work_blocks_with_small_file_structural_warning(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("def main():\n    pass\n\nif __name__ == \"__main__\":\n    main()\n", encoding="utf-8")
            provider = _QueueProvider(
                [
                    _plan_response(files_to_modify=["main.py"]),
                    _risky_small_file_response(),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Update CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "work_metadata.json")
            diff_warnings = _read_json(session_dir / "diff_warnings.json")

            self.assertEqual(metadata["status"], "blocked")
            self.assertEqual(metadata["reason"], "Work blocked by structural edit warning.")
            self.assertTrue(any("Small file structural edit risk" in warning for warning in diff_warnings["warnings"]))

    def test_sandbox_failure_then_repair_success(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('old')\n", encoding="utf-8")
            provider = _QueueProvider(
                [
                    _plan_response(files_to_modify=["main.py"]),
                    _rewrite_main_response("import sys\nsys.exit(1)\n"),
                    _rewrite_main_response("print('ok')\n"),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Fix CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "work_metadata.json")

            self.assertEqual(metadata["repairs_used"], 1)
            self.assertEqual(metadata["status"], "ready_to_apply")
            self.assertGreaterEqual([step["step"] for step in metadata["steps"]].count("sandbox_test"), 2)

    def test_max_retries_reached(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _QueueProvider(
                [
                    _plan_response(files_to_create=["main.py"]),
                    '{"foo": []}',
                    '{"foo": []}',
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Create CLI", "--path", str(root), "--max-retries", "1"])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Diff retry limit reached", result.output)
            metadata = _read_json(_only_session(root) / "work_metadata.json")
            self.assertEqual(metadata["status"], "blocked")
            self.assertEqual(metadata["reason"], "Diff retry limit reached.")

    def test_max_repairs_reached(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('old')\n", encoding="utf-8")
            provider = _QueueProvider(
                [
                    _plan_response(files_to_modify=["main.py"]),
                    _rewrite_main_response("import sys\nsys.exit(1)\n"),
                    _rewrite_main_response("import sys\nsys.exit(1)\n"),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Fix CLI", "--path", str(root), "--max-repairs", "1"])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Repair limit reached", result.output)
            metadata = _read_json(_only_session(root) / "work_metadata.json")
            self.assertEqual(metadata["status"], "blocked")
            self.assertEqual(metadata["reason"], "Repair limit reached.")

    def test_timeline_contains_work_events(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _QueueProvider(
                [
                    _plan_response(files_to_create=["main.py"]),
                    _create_main_response("print('ok')\n"),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Create CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            events = [event["event"] for event in read_timeline(_only_session(root))]

            self.assertIn("work_started", events)
            self.assertIn("work_step_started", events)
            self.assertIn("work_step_completed", events)
            self.assertIn("work_ready_to_apply", events)
            self.assertIn("work_stopped", events)

    def test_work_accepts_full_file_rewrite_returned_as_operation_with_content(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('old')\n", encoding="utf-8")
            provider = _QueueProvider(
                [
                    _plan_response(files_to_modify=["main.py"]),
                    json.dumps(
                        {
                            "changes": [
                                {
                                    "path": "main.py",
                                    "change_type": "modified",
                                    "mode": "operation_based_edit",
                                    "operation": "full_file_rewrite",
                                    "content": "print('ok')\n",
                                }
                            ]
                        }
                    ),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["work", "Update CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "work_metadata.json")
            self.assertEqual(metadata["status"], "ready_to_apply")
            self.assertNotIn("Unknown operation", result.output)

    def test_apply_high_risk_warning_requires_literal_apply(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('old')\n", encoding="utf-8")
            session = create_session(root, "Update CLI", command="plan")
            session = update_session_status(session, "diff_validated")
            write_patch_file(
                session.path / "diff.patch",
                (
                    "diff --git a/main.py b/main.py\n"
                    "--- a/main.py\n"
                    "+++ b/main.py\n"
                    "@@ -1 +1 @@\n"
                    "-print('old')\n"
                    "+print('new')\n"
                ),
            )
            write_session_json(
                session,
                "file_changes.json",
                {"changes": [{"path": "main.py", "change_type": "modified", "mode": "full_file_rewrite"}]},
            )
            write_session_json(
                session,
                "diff_validation.json",
                {
                    "status": "passed",
                    "changes": [{"path": "main.py", "change_type": "modified", "mode": "full_file_rewrite"}],
                    "warnings": [],
                },
            )
            write_session_json(
                session,
                "diff_warnings.json",
                {"warnings": ["Small file structural edit risk: main.py received fragile local edits."]},
            )

            cancelled = runner.invoke(app, ["apply", "--path", str(root)], input="y\n")
            applied = runner.invoke(app, ["apply", "--path", str(root)], input="apply\n")

            self.assertEqual(cancelled.exit_code, 0, cancelled.output)
            self.assertIn("Type 'apply' to confirm", cancelled.output)
            self.assertEqual(applied.exit_code, 0, applied.output)
            self.assertEqual((root / "main.py").read_text(encoding="utf-8"), "print('new')\n")

    def test_work_help(self) -> None:
        runner = CliRunner()

        result = runner.invoke(app, ["work", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--max-retries", result.output)
        self.assertIn("--max-plan-retries", result.output)
        self.assertIn("--max-repairs", result.output)


def _plan_response(*, files_to_create: list[str] | None = None, files_to_modify: list[str] | None = None) -> str:
    return json.dumps(
        {
            "summary": "Update CLI.",
            "project_reading": "Python project.",
            "files_involved": (files_to_create or []) + (files_to_modify or []),
            "expected_behavior": ["python main.py exits successfully"],
            "acceptance_criteria": ["Command runs."],
            "suggested_verification_commands": [f'"{sys.executable}" main.py'],
            "files_to_create": files_to_create or [],
            "files_to_modify": files_to_modify or [],
            "files_not_to_modify": [],
            "steps": ["Update main.py."],
            "risks": [],
            "next_command": "trevvos diff",
        }
    )


def _create_main_response(content: str) -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "main.py",
                    "change_type": "created",
                    "mode": "operation_based_edit",
                    "operation": "create_file",
                    "content": content,
                }
            ]
        }
    )


def _rewrite_main_response(content: str) -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "main.py",
                    "change_type": "modified",
                    "mode": "full_file_rewrite",
                    "content": content,
                }
            ]
        }
    )


def _missing_target_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "main.py",
                    "change_type": "modified",
                    "mode": "operation_based_edit",
                    "operation": "insert_after_line",
                    "target": "missing line",
                    "insert": "print('ok')\\n",
                }
            ]
        }
    )


def _plan_response_with_uncovered_cli_command() -> str:
    payload = json.loads(_plan_response(files_to_modify=["main.py"]))
    payload["expected_behavior"] = ["python main.py sqrt 9 prints 3.0"]
    payload["suggested_verification_commands"] = ["python -m py_compile calculator.py main.py"]
    return json.dumps(payload)


def _risky_small_file_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "main.py",
                    "change_type": "modified",
                    "mode": "operation_based_edit",
                    "operation": "insert_after_line",
                    "target": "def main():",
                    "insert": "    print('ok')\n",
                },
                {
                    "path": "main.py",
                    "change_type": "modified",
                    "mode": "operation_based_edit",
                    "operation": "append_to_file",
                    "insert": "\n# appended\n",
                },
            ]
        }
    )


def _only_session(root: Path) -> Path:
    sessions = list((root / ".trevvos" / "sessions").iterdir())
    self = None
    return sessions[0]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class _QueueProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses

    def generate(self, prompt: str) -> str:
        if not self.responses:
            raise AssertionError("No fake provider responses left.")
        return self.responses.pop(0)


if __name__ == "__main__":
    unittest.main()
