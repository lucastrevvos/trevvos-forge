import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.repair_workflow import (
    build_repair_context,
    build_repair_metadata,
    build_repair_prompt,
    write_repair_metadata,
)
from trevvos_forge.sessions import create_session, write_session_json, write_session_text


class RepairWorkflowTests(unittest.TestCase):
    def test_repair_fails_without_repairable_evidence(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update CLI", command="plan")
            write_session_json(session, "plan.json", {})
            write_session_text(session, "plan.md", "Plan.")
            write_session_json(session, "file_changes.json", {"changes": []})

            result = runner.invoke(app, ["repair", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("No valid diff found to repair.", result.output)
            self.assertIn("trevvos diff --retry", result.output)
            self.assertTrue((session.path / "repair_metadata.json").exists())
            self.assertFalse((session.path / "repair_prompt.md").exists())
            self.assertFalse((session.path / "operation_error.json").exists())

            metadata = json.loads((session.path / "repair_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "not_repairable")
            self.assertEqual(metadata["reason"], "missing_valid_diff")
            self.assertEqual(metadata["suggested_next_command"], "trevvos diff --retry")

    def test_repair_does_not_call_provider_without_valid_diff(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update CLI", command="plan")
            write_session_json(session, "plan.json", {})
            write_session_text(session, "plan.md", "Plan.")
            write_session_json(
                session,
                "semantic_review.json",
                {
                    "warnings": [
                        "Suggested verification commands exist, but sandbox tests were not run.",
                        "Plan verification commands were not fully executed.",
                    ]
                },
            )

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["repair", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("No valid diff found to repair.", result.output)
            build_provider.assert_not_called()
            self.assertTrue((session.path / "repair_metadata.json").exists())
            self.assertFalse((session.path / "repair_prompt.md").exists())

            metadata = json.loads((session.path / "repair_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "not_repairable")

    def test_repair_does_not_treat_sandbox_not_run_as_repairable_without_diff(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update CLI", command="plan")
            write_session_json(session, "plan.json", {})
            write_session_text(session, "plan.md", "Plan.")
            write_session_json(
                session,
                "semantic_review.json",
                {
                    "verdict": "needs_human_review",
                    "warnings": ["Suggested verification commands exist, but sandbox tests were not run."],
                    "plan_review": {"plan_commands_executed": "no"},
                },
            )

            result = runner.invoke(app, ["repair", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            metadata = json.loads((session.path / "repair_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "not_repairable")
            self.assertEqual(metadata["reason"], "missing_valid_diff")

    def test_repair_fails_with_valid_diff_but_no_repairable_evidence(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update CLI", command="plan")
            write_session_json(session, "plan.json", {})
            write_session_text(session, "plan.md", "Plan.")
            write_session_json(
                session,
                "file_changes.json",
                {"changes": [{"path": "main.py", "change_type": "modified", "mode": "full_file_rewrite"}]},
            )
            write_session_text(session, "diff.patch", "diff --git a/main.py b/main.py\n")

            result = runner.invoke(app, ["repair", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("No repairable failure found for current session.", result.output)

    def test_build_repair_context_with_sandbox_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('broken')\n", encoding="utf-8")
            session = _create_repair_session(root)

            context = build_repair_context(session=session, repo_root=root)

            self.assertEqual(context["reason"], "sandbox_failed")
            self.assertIn("Use argparse", context["plan"]["acceptance_criteria"])
            self.assertIn("python main.py add 2 3", context["plan"]["suggested_verification_commands"])
            self.assertIn("NameError", context["sandbox_test_output_tail"])
            self.assertEqual(context["current_files"][0]["path"], "main.py")
            self.assertIn("1 | print('broken')", context["current_files"][0]["content_with_line_numbers"])

    def test_build_repair_context_with_review_concerns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('functions')\n", encoding="utf-8")
            session = create_session(root, "Create executable CLI", command="plan")
            write_session_json(session, "plan.json", {"acceptance_criteria": ["Execute commands"]})
            write_session_text(session, "plan.md", "Plan.")
            write_session_json(
                session,
                "file_changes.json",
                {"changes": [{"path": "main.py", "change_type": "modified", "mode": "full_file_rewrite"}]},
            )
            write_session_text(session, "diff.patch", "diff --git a/main.py b/main.py\n")
            write_session_json(
                session,
                "semantic_review.json",
                {"concerns": ["Patch lists functions but does not execute CLI commands."]},
            )

            context = build_repair_context(session=session, repo_root=root)

            self.assertEqual(context["reason"], "semantic_review_concerns")
            self.assertIn("Patch lists functions", json.dumps(context["semantic_review"]))

    def test_build_repair_prompt_contains_evidence_and_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('broken')\n", encoding="utf-8")
            session = _create_repair_session(root)

            prompt = build_repair_prompt(build_repair_context(session=session, repo_root=root))

            self.assertIn("acceptance_criteria", prompt)
            self.assertIn("NameError", prompt)
            self.assertIn("Do not reimplement from scratch", prompt)
            self.assertIn("Preserve files listed in files_not_to_modify", prompt)
            self.assertIn('"changes"', prompt)

    def test_repair_with_fake_provider_generates_valid_diff_without_applying(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _git_init(root)
            main_path = root / "main.py"
            main_path.write_text("print('broken')\n", encoding="utf-8")
            session = _create_repair_session(root)

            provider = _FakeProvider(
                """
{
  "changes": [
    {
      "path": "main.py",
      "change_type": "modified",
      "mode": "full_file_rewrite",
      "content": "def main():\\n    print('fixed')\\n\\nif __name__ == '__main__':\\n    main()\\n"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["repair", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Repair generated a new diff successfully.", result.output)
            self.assertEqual(main_path.read_text(encoding="utf-8"), "print('broken')\n")
            self.assertTrue((session.path / "diff.patch").exists())
            self.assertTrue((session.path / "repair_metadata.json").exists())
            self.assertTrue((session.path / "repair_prompt.md").exists())
            self.assertTrue((session.path / "repair_raw_response.json").exists())

            metadata = json.loads((session.path / "repair_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "succeeded")
            self.assertEqual(metadata["repair_count"], 1)
            self.assertEqual(metadata["reason"], "sandbox_failed")

    def test_repair_failure_writes_metadata_and_operation_error(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('broken')\n", encoding="utf-8")
            session = _create_repair_session(root)
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
      "insert": "print('fixed')\\n"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["repair", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertTrue((session.path / "repair_metadata.json").exists())
            self.assertTrue((session.path / "operation_error.json").exists())

            metadata = json.loads((session.path / "repair_metadata.json").read_text(encoding="utf-8"))
            operation_error = json.loads((session.path / "operation_error.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "failed")
            self.assertEqual(metadata["repair_count"], 1)
            self.assertEqual(operation_error["error_type"], "target_not_found")

    def test_repair_count_increments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update CLI", command="plan")

            first = build_repair_metadata(
                session=session,
                prompt_ref="repair_file_changes@1.0.0",
                status="failed",
                reason="sandbox_failed",
                evidence_used=[],
            )
            write_repair_metadata(session, first)
            second = build_repair_metadata(
                session=session,
                prompt_ref="repair_file_changes@1.0.0",
                status="started",
                reason="sandbox_failed",
                evidence_used=[],
            )

            self.assertEqual(first["repair_count"], 1)
            self.assertEqual(second["repair_count"], 2)


def _create_repair_session(root: Path):
    session = create_session(root, "Create executable CLI", command="plan")
    write_session_json(
        session,
        "plan.json",
        {
            "expected_behavior": ["python main.py add 2 3 prints 5"],
            "acceptance_criteria": ["Use argparse"],
            "suggested_verification_commands": ["python main.py add 2 3"],
            "files_to_modify": ["main.py"],
            "files_not_to_modify": ["calculator.py"],
        },
    )
    write_session_text(session, "plan.md", "## Acceptance criteria\n- Use argparse\n")
    write_session_json(
        session,
        "file_changes.json",
        {"changes": [{"path": "main.py", "change_type": "modified", "mode": "full_file_rewrite"}]},
    )
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
    write_session_text(session, "diff.patch", "diff --git a/main.py b/main.py\n")
    write_session_json(session, "sandbox_test_results.json", {"mode": "sandbox", "status": "failed"})
    write_session_text(session, "sandbox_test_output.log", "Traceback\nNameError: name 'add' is not defined\n")
    write_session_json(session, "semantic_review.json", {"concerns": []})
    return session


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


if __name__ == "__main__":
    unittest.main()
