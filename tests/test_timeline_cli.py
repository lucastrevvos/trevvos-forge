import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.sessions import create_session, write_patch_file, write_session_json, write_session_text
from trevvos_forge.timeline import read_timeline


class TimelineCliTests(unittest.TestCase):
    def test_plan_records_started_and_completed(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            provider = _FakeProvider(_plan_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["plan", "Update README", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            session_dir = next((root / ".trevvos" / "sessions").iterdir())
            events = read_timeline(session_dir)

            self.assertEqual(events[0]["event"], "plan_started")
            self.assertIn("plan_completed", [event["event"] for event in events])

    def test_plan_failure_and_retry_record_events(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _QueueProvider(["invalid plan", _plan_response()])

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                initial = runner.invoke(app, ["plan", "Update README", "--path", str(root)])
                retry = runner.invoke(app, ["plan", "--retry", "--path", str(root)])

            self.assertEqual(initial.exit_code, 1, initial.output)
            self.assertEqual(retry.exit_code, 0, retry.output)
            session_dir = next((root / ".trevvos" / "sessions").iterdir())
            events = [event["event"] for event in read_timeline(session_dir)]

            self.assertIn("plan_failed", events)
            self.assertIn("plan_retry_started", events)
            self.assertIn("plan_retry_completed", events)

    def test_diff_schema_error_records_diff_failed_reason(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update CLI", command="plan")
            write_session_text(session, "context.md", "context")
            write_session_text(session, "plan.md", "plan")
            provider = _FakeProvider('{"foo": []}')

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            events = read_timeline(session.path)
            diff_failed = [event for event in events if event["event"] == "diff_failed"]

            self.assertTrue(diff_failed)
            self.assertEqual(diff_failed[-1]["reason"], "invalid_file_changes_schema")
            self.assertTrue(any(event["event"] == "file_changes_error" for event in events))

    def test_diff_success_records_completed(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('old')\n", encoding="utf-8")
            session = create_session(root, "Update CLI", command="plan")
            write_session_text(session, "context.md", "context")
            write_session_text(session, "plan.md", "plan")
            write_session_json(
                session,
                "selected_files.json",
                {
                    "selected_files": [
                        {
                            "path": "main.py",
                            "total_lines": 1,
                            "included_ranges": [{"start_line": 1, "end_line": 1}],
                        }
                    ]
                },
            )
            provider = _FakeProvider(
                """
{
  "changes": [
    {
      "path": "main.py",
      "change_type": "modified",
      "mode": "full_file_rewrite",
      "content": "print('new')\\n"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            events = read_timeline(session.path)
            completed = [event for event in events if event["event"] == "diff_completed"]

            self.assertTrue(completed)
            self.assertEqual(completed[-1]["status"], "succeeded")
            self.assertEqual(completed[-1]["files_changed"], ["main.py"])

    def test_sandbox_test_records_events(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "test", command="plan")
            write_session_json(
                session,
                "plan.json",
                {"suggested_verification_commands": [f'"{sys.executable}" main.py']},
            )
            write_patch_file(session.path / "diff.patch", _create_file_patch("main.py", "print('ok')\n"))

            result = runner.invoke(
                app,
                ["test", "--sandbox", "--plan-commands", "--yes", "--path", str(root)],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            events = read_timeline(session.path)

            self.assertIn("sandbox_test_started", [event["event"] for event in events])
            completed = [event for event in events if event["event"] == "sandbox_test_completed"]
            self.assertTrue(completed)
            self.assertEqual(completed[-1]["test_status"], "passed")

    def test_repair_without_valid_diff_records_not_repairable(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update CLI", command="plan")
            write_session_json(session, "plan.json", {})
            write_session_text(session, "plan.md", "Plan.")

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["repair", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            build_provider.assert_not_called()
            events = read_timeline(session.path)
            not_repairable = [event for event in events if event["event"] == "repair_not_repairable"]

            self.assertTrue(not_repairable)
            self.assertEqual(not_repairable[-1]["status"], "not_repairable")
            self.assertEqual(not_repairable[-1]["reason"], "missing_valid_diff")


def _plan_response() -> str:
    return json.dumps(
        {
            "summary": "Update README.",
            "project_reading": "Small project.",
            "files_involved": ["README.md"],
            "expected_behavior": ["README is updated"],
            "acceptance_criteria": ["README contains the requested text"],
            "suggested_verification_commands": [],
            "files_to_create": [],
            "files_to_modify": ["README.md"],
            "files_not_to_modify": [],
            "steps": ["Edit README.md."],
            "risks": [],
            "next_command": "trevvos diff",
        }
    )


def _create_file_patch(path: str, content: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"+{content.rstrip()}\n"
    )


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


class _QueueProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses

    def generate(self, prompt: str) -> str:
        if not self.responses:
            raise AssertionError("No fake provider responses left.")
        return self.responses.pop(0)


if __name__ == "__main__":
    unittest.main()
