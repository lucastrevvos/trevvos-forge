import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput
from trevvos_forge.plan_constraints import (
    build_plan_constraints_prompt_section,
    check_file_changes_against_plan_constraints,
    load_plan_constraints,
)
from trevvos_forge.sessions import create_session, write_session_json, write_session_text


class PlanConstraintsTests(unittest.TestCase):
    def test_legacy_plan_returns_empty_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            (session_dir / "plan.json").write_text(
                json.dumps(
                    {
                        "summary": "Legacy.",
                        "project_reading": "Project.",
                        "files_involved": ["README.md"],
                        "steps": ["Edit."],
                        "risks": ["None."],
                        "next_command": "trevvos diff",
                    }
                ),
                encoding="utf-8",
            )

            constraints = load_plan_constraints(session_dir)

            self.assertEqual(constraints["expected_behavior"], [])
            self.assertEqual(constraints["acceptance_criteria"], [])
            self.assertEqual(constraints["suggested_verification_commands"], [])
            self.assertEqual(constraints["files_to_create"], [])
            self.assertEqual(constraints["files_to_modify"], [])
            self.assertEqual(constraints["files_not_to_modify"], [])

    def test_prompt_section_contains_constraints(self) -> None:
        section = build_plan_constraints_prompt_section(
            {
                "expected_behavior": ["python main.py add 2 3 prints 5"],
                "acceptance_criteria": ["Uses argparse"],
                "suggested_verification_commands": ["python main.py add 2 3"],
                "files_to_create": ["main.py"],
                "files_to_modify": [],
                "files_not_to_modify": ["calculator.py"],
            }
        )

        self.assertIn("Expected behavior", section)
        self.assertIn("Acceptance criteria", section)
        self.assertIn("Suggested verification commands", section)
        self.assertIn("Files to create", section)
        self.assertIn("Files to modify", section)
        self.assertIn("Files not to modify", section)
        self.assertIn("calculator.py", section)

    def test_constraints_pass_when_expected_file_is_created(self) -> None:
        result = check_file_changes_against_plan_constraints(
            file_changes=FileChangesOutput(
                changes=[
                    FileChange(
                        path="main.py",
                        change_type="created",
                        content="print('ok')\n",
                        mode="operation_based_edit",
                        operation="create_file",
                    )
                ]
            ),
            constraints={
                "files_to_create": ["main.py"],
                "files_to_modify": [],
                "files_not_to_modify": ["calculator.py"],
            },
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["warnings"], [])

    def test_constraints_fail_when_file_is_marked_not_to_modify(self) -> None:
        result = check_file_changes_against_plan_constraints(
            file_changes=FileChangesOutput(
                changes=[
                    FileChange(
                        path="calculator.py",
                        change_type="modified",
                        content="print('bad')\n",
                        mode="full_file_rewrite",
                    )
                ]
            ),
            constraints={"files_not_to_modify": ["calculator.py"]},
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("calculator.py is marked as files_not_to_modify.", result["violations"])

    def test_constraints_warn_when_expected_created_file_is_missing(self) -> None:
        result = check_file_changes_against_plan_constraints(
            file_changes=FileChangesOutput(
                changes=[
                    FileChange(
                        path="README.md",
                        change_type="modified",
                        content="# Updated\n",
                        mode="full_file_rewrite",
                    )
                ]
            ),
            constraints={"files_to_create": ["main.py"]},
        )

        self.assertEqual(result["status"], "warning")
        self.assertIn("Plan expected creation of main.py", result["warnings"][0])

    def test_constraints_warn_when_file_is_outside_files_to_modify(self) -> None:
        result = check_file_changes_against_plan_constraints(
            file_changes=FileChangesOutput(
                changes=[
                    FileChange(
                        path="README.md",
                        change_type="modified",
                        content="# Updated\n",
                        mode="full_file_rewrite",
                    )
                ]
            ),
            constraints={"files_to_modify": ["main.py"]},
        )

        self.assertEqual(result["status"], "warning")
        self.assertIn("README.md is outside files_to_modify", result["warnings"][0])


class PlanConstraintsCliTests(unittest.TestCase):
    def test_diff_blocks_files_not_to_modify_violation(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            session = _create_diff_session(
                root,
                plan_constraints={
                    "files_to_create": ["main.py"],
                    "files_to_modify": [],
                    "files_not_to_modify": ["calculator.py"],
                },
                selected_paths=["calculator.py"],
            )
            provider = _FakeProvider(
                """
{
  "changes": [
    {
      "path": "calculator.py",
      "change_type": "modified",
      "mode": "full_file_rewrite",
      "content": "def add(a, b):\\n    return a + b\\n\\ndef subtract(a, b):\\n    return a - b\\n"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("files_not_to_modify", result.output)
            self.assertTrue((session.path / "plan_constraints_check.json").exists())
            self.assertFalse((session.path / "diff_validation.json").exists())

            payload = json.loads((session.path / "plan_constraints_check.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertIn("calculator.py is marked as files_not_to_modify.", payload["violations"])

    def test_diff_with_plan_constraint_warning_continues(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Old\n", encoding="utf-8")
            session = _create_diff_session(
                root,
                plan_constraints={
                    "files_to_create": [],
                    "files_to_modify": ["main.py"],
                    "files_not_to_modify": [],
                },
                selected_paths=["README.md"],
            )
            provider = _FakeProvider(
                """
{
  "changes": [
    {
      "path": "README.md",
      "change_type": "modified",
      "mode": "full_file_rewrite",
      "content": "# New\\n"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("README.md is outside files_to_modify", result.output)
            self.assertTrue((session.path / "diff.patch").exists())

            payload = json.loads((session.path / "plan_constraints_check.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "warning")


def _create_diff_session(root: Path, *, plan_constraints: dict, selected_paths: list[str]):
    session = create_session(root, "Create CLI", command="plan")
    write_session_text(session, "context.md", "Context")
    write_session_text(session, "plan.md", "Plan")
    write_session_json(
        session,
        "plan.json",
        {
            "summary": "Create CLI.",
            "project_reading": "Python project.",
            "files_involved": selected_paths,
            "expected_behavior": [],
            "acceptance_criteria": [],
            "suggested_verification_commands": [],
            "files_to_create": plan_constraints.get("files_to_create", []),
            "files_to_modify": plan_constraints.get("files_to_modify", []),
            "files_not_to_modify": plan_constraints.get("files_not_to_modify", []),
            "steps": ["Generate diff."],
            "risks": [],
            "next_command": "trevvos diff",
        },
    )
    write_session_json(
        session,
        "selected_files.json",
        {
            "selected_files": [
                {
                    "path": path,
                    "size_bytes": 10,
                    "score": 10,
                    "reason": "test",
                    "is_truncated": False,
                    "included_ranges": [{"start_line": 1, "end_line": 1}],
                    "total_lines": 1,
                    "markdown_headings": [],
                }
                for path in selected_paths
            ]
        },
    )
    return session


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


if __name__ == "__main__":
    unittest.main()
