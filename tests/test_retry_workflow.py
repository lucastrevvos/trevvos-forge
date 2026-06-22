import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.retry_workflow import build_retry_context, build_retry_prompt
from trevvos_forge.sessions import create_session, write_session_json, write_session_text


class RetryWorkflowTests(unittest.TestCase):
    def test_retry_fails_without_operation_error(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update CLI", command="plan")
            write_session_text(session, "context.md", "context")
            write_session_text(session, "plan.md", "plan")

            result = runner.invoke(app, ["diff", "--retry", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("No operation_error.json found for current session.", result.output)
            self.assertFalse((session.path / "operation_error.json").exists())

    def test_build_retry_prompt_includes_previous_error_and_numbered_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("import argparse\n\nprint('hello')\n", encoding="utf-8")
            session = create_session(root, "Update CLI", command="plan")
            write_session_text(session, "context.md", "workspace context")
            write_session_text(session, "plan.md", "Plan.")
            write_session_json(
                session,
                "operation_error.json",
                {
                    "status": "failed",
                    "error_type": "target_not_found",
                    "message": "Operation insert_after_line target not found in main.py: missing line",
                    "path": "main.py",
                    "operation": "insert_after_line",
                    "target": "missing line",
                    "suggested_resolution": "Use replace_block or full_file_rewrite.",
                },
            )

            context = build_retry_context(session=session, repo_root=root)
            prompt = build_retry_prompt(context)

            self.assertIn("target_not_found", prompt)
            self.assertIn("main.py", prompt)
            self.assertIn("insert_after_line", prompt)
            self.assertIn("missing line", prompt)
            self.assertIn("Use replace_block or full_file_rewrite.", prompt)
            self.assertIn("1 | import argparse", prompt)
            self.assertIn("Do not repeat invalid target", prompt)
            self.assertIn("nao use o mesmo target inexistente", prompt.lower())

    def test_retry_with_fake_provider_succeeds_and_clears_operation_error(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            main_path = root / "main.py"
            main_path.write_text("print('hello')\n", encoding="utf-8")
            session = _create_retry_session(root)

            provider = _FakeProvider(
                """
{
  "changes": [
    {
      "path": "main.py",
      "change_type": "modified",
      "mode": "full_file_rewrite",
      "content": "import argparse\\n\\ndef main():\\n    print('fixed')\\n\\nif __name__ == '__main__':\\n    main()\\n"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["diff", "--retry", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Retry generated a new diff successfully", result.output)
            self.assertFalse((session.path / "operation_error.json").exists())
            self.assertFalse((session.path / "operation_error.md").exists())
            self.assertTrue((session.path / "diff.patch").exists())
            self.assertTrue((session.path / "retry_metadata.json").exists())

            metadata = json.loads((session.path / "retry_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "succeeded")
            self.assertEqual(metadata["retry_count"], 1)
            self.assertEqual(metadata["previous_error_type"], "target_not_found")
            self.assertEqual(metadata["previous_operation"], "insert_after_line")
            self.assertEqual(metadata["prompt"], "file_changes_retry@1.0.0")

    def test_retry_failure_writes_new_operation_error_and_failed_metadata(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('hello')\n", encoding="utf-8")
            session = _create_retry_session(root)

            provider = _FakeProvider(
                """
{
  "changes": [
    {
      "path": "main.py",
      "change_type": "modified",
      "mode": "operation_based_edit",
      "operation": "insert_after_line",
      "target": "still missing",
      "insert": "print('fixed')"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["diff", "--retry", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Retry failed.", result.output)
            self.assertTrue((session.path / "operation_error.json").exists())
            self.assertTrue((session.path / "operation_error.md").exists())

            operation_error = json.loads((session.path / "operation_error.json").read_text(encoding="utf-8"))
            metadata = json.loads((session.path / "retry_metadata.json").read_text(encoding="utf-8"))

            self.assertEqual(operation_error["error_type"], "target_not_found")
            self.assertEqual(operation_error["target"], "still missing")
            self.assertEqual(metadata["status"], "failed")
            self.assertEqual(metadata["retry_count"], 1)

    def test_retry_count_increments_on_manual_calls(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('hello')\n", encoding="utf-8")
            session = _create_retry_session(root)
            write_session_json(
                session,
                "retry_metadata.json",
                {
                    "retry": True,
                    "retry_count": 1,
                    "previous_error_type": "target_not_found",
                    "status": "failed",
                },
            )

            provider = _FakeProvider(
                """
{
  "changes": [
    {
      "path": "main.py",
      "change_type": "modified",
      "mode": "operation_based_edit",
      "operation": "insert_after_line",
      "target": "still missing",
      "insert": "print('fixed')"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                runner.invoke(app, ["diff", "--retry", "--path", str(root)])

            metadata = json.loads((session.path / "retry_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["retry_count"], 2)


def _create_retry_session(root: Path):
    session = create_session(root, "Update CLI", command="plan")
    write_session_text(session, "context.md", "## File: main.py\nprint('hello')\n")
    write_session_text(session, "plan.md", "Plan.")
    write_session_json(
        session,
        "selected_files.json",
        {
            "instruction": "Update CLI",
            "workspace_root": str(root),
            "total_chars": 14,
            "selected_files": [
                {
                    "path": "main.py",
                    "size_bytes": 14,
                    "score": 10,
                    "reason": "test fixture",
                    "is_truncated": False,
                    "included_ranges": [{"start_line": 1, "end_line": 1}],
                    "total_lines": 1,
                    "markdown_headings": [],
                }
            ],
        },
    )
    write_session_json(
        session,
        "operation_error.json",
        {
            "status": "failed",
            "error_type": "target_not_found",
            "message": "Operation insert_after_line target not found in main.py: missing line",
            "path": "main.py",
            "operation": "insert_after_line",
            "target": "missing line",
            "suggested_resolution": "Use replace_block or full_file_rewrite for small files.",
        },
    )
    write_session_text(session, "operation_error.md", "# Operation Error\n")
    return session


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


if __name__ == "__main__":
    unittest.main()
