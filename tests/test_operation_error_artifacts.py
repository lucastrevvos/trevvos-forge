import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.operation_error_artifacts import (
    build_operation_error_artifact,
    write_operation_error_artifacts,
)
from trevvos_forge.sessions import create_session, write_session_text


class OperationErrorArtifactTests(unittest.TestCase):
    def test_target_not_found_artifact(self) -> None:
        artifact = build_operation_error_artifact(
            "Operation insert_after_line target not found in main.py: missing line"
        )

        self.assertEqual(artifact.status, "failed")
        self.assertEqual(artifact.error_type, "target_not_found")
        self.assertEqual(artifact.path, "main.py")
        self.assertEqual(artifact.operation, "insert_after_line")
        self.assertEqual(artifact.target, "missing line")
        self.assertIn("choose an existing target", artifact.suggested_resolution)

    def test_ambiguous_target_artifact(self) -> None:
        artifact = build_operation_error_artifact(
            "Operation replace_block target is ambiguous in example.py: def same():\n"
        )

        self.assertEqual(artifact.error_type, "ambiguous_target")
        self.assertEqual(artifact.path, "example.py")
        self.assertEqual(artifact.operation, "replace_block")
        self.assertEqual(artifact.target, "def same():\n")
        self.assertIn("more specific unique target", artifact.suggested_resolution)

    def test_mixed_modes_artifact(self) -> None:
        artifact = build_operation_error_artifact(
            "Cannot compose mixed file change modes for: README.md"
        )

        self.assertEqual(artifact.error_type, "mixed_modes")
        self.assertEqual(artifact.path, "README.md")
        self.assertIsNone(artifact.operation)
        self.assertIsNone(artifact.target)
        self.assertIn("one edit mode per file", artifact.suggested_resolution)

    def test_write_operation_error_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "change request", command="plan")

            artifact = write_operation_error_artifacts(
                session,
                "Operation insert_after_line target not found in main.py: missing line",
            )

            payload = json.loads((session.path / "operation_error.json").read_text(encoding="utf-8"))
            markdown = (session.path / "operation_error.md").read_text(encoding="utf-8")

            self.assertEqual(payload["error_type"], "target_not_found")
            self.assertEqual(payload["path"], "main.py")
            self.assertEqual(payload["operation"], "insert_after_line")
            self.assertEqual(payload["target"], "missing line")
            self.assertEqual(artifact.error_type, "target_not_found")
            self.assertIn("# Operation Error", markdown)
            self.assertIn("missing line", markdown)

    def test_write_ambiguous_target_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "change request", command="plan")

            write_operation_error_artifacts(
                session,
                "Operation replace_block target is ambiguous in example.py: def same():\n",
            )

            payload = json.loads((session.path / "operation_error.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["error_type"], "ambiguous_target")
            self.assertEqual(payload["path"], "example.py")
            self.assertEqual(payload["operation"], "replace_block")

    def test_write_mixed_modes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "change request", command="plan")

            write_operation_error_artifacts(
                session,
                "Cannot compose mixed file change modes for: README.md",
            )

            payload = json.loads((session.path / "operation_error.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["error_type"], "mixed_modes")
            self.assertEqual(payload["path"], "README.md")
            self.assertIsNone(payload["operation"])


class OperationErrorCliTests(unittest.TestCase):
    def test_diff_failure_writes_operation_error_artifacts_and_prints_paths(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('hello')\n", encoding="utf-8")
            session = create_session(root, "Update CLI", command="plan")
            write_session_text(session, "context.md", "## File: main.py\nprint('hello')\n")
            write_session_text(session, "plan.md", "Plan.")

            provider = _FakeProvider(
                """
{
  "changes": [
    {
      "path": "main.py",
      "change_type": "modified",
      "mode": "operation_based_edit",
      "operation": "insert_after_line",
      "target": "missing line",
      "insert": "print('new')"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("operation_error.json", result.output)
            self.assertIn("operation_error.md", result.output)

            payload = json.loads((session.path / "operation_error.json").read_text(encoding="utf-8"))
            markdown = (session.path / "operation_error.md").read_text(encoding="utf-8")

            self.assertEqual(payload["error_type"], "target_not_found")
            self.assertEqual(payload["path"], "main.py")
            self.assertEqual(payload["operation"], "insert_after_line")
            self.assertEqual(payload["target"], "missing line")
            self.assertIn("Use replace_block or full_file_rewrite", markdown)
            self.assertTrue((session.path / "diff_error.txt").exists())


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


if __name__ == "__main__":
    unittest.main()
