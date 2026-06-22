import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.structured_outputs import PlanOutput, parse_plan_output


class PlanOutputTests(unittest.TestCase):
    def test_parser_defaults_behavior_fields_for_legacy_plan(self) -> None:
        plan = parse_plan_output(
            json.dumps(
                {
                    "summary": "Update docs.",
                    "project_reading": "Small project.",
                    "files_involved": ["README.md"],
                    "steps": ["Edit README.md."],
                    "risks": ["None."],
                    "next_command": "trevvos diff",
                }
            )
        )

        self.assertEqual(plan.expected_behavior, [])
        self.assertEqual(plan.acceptance_criteria, [])
        self.assertEqual(plan.suggested_verification_commands, [])
        self.assertEqual(plan.files_to_create, [])
        self.assertEqual(plan.files_to_modify, [])
        self.assertEqual(plan.files_not_to_modify, [])

    def test_plan_markdown_renders_behavior_first_sections(self) -> None:
        plan = PlanOutput(
            summary="Create CLI.",
            project_reading="Python project.",
            files_involved=["main.py", "calculator.py"],
            expected_behavior=[
                "`python main.py add 2 3` prints `5`.",
                "`python main.py divide 10 0` prints a friendly error.",
            ],
            acceptance_criteria=[
                "The CLI uses argparse.",
                "Subcommands are registered before parse_args().",
                "Runtime dispatch happens inside main().",
            ],
            suggested_verification_commands=[
                "python -m py_compile main.py calculator.py",
                "python main.py add 2 3",
            ],
            files_to_create=["main.py"],
            files_to_modify=[],
            files_not_to_modify=["calculator.py"],
            steps=["Create main.py."],
            risks=["Division by zero handling."],
            next_command="trevvos diff",
        )

        markdown = plan.to_markdown()

        self.assertIn("## Expected behavior", markdown)
        self.assertIn("`python main.py add 2 3` prints `5`.", markdown)
        self.assertIn("## Acceptance criteria", markdown)
        self.assertIn("The CLI uses argparse.", markdown)
        self.assertIn("## Suggested commands to verify", markdown)
        self.assertIn("python -m py_compile main.py calculator.py", markdown)
        self.assertIn("## Files to create", markdown)
        self.assertIn("- main.py", markdown)
        self.assertIn("## Files to modify", markdown)
        self.assertIn("- none", markdown)
        self.assertIn("## Files not to modify", markdown)
        self.assertIn("- calculator.py", markdown)


class PlanCliTests(unittest.TestCase):
    def test_fake_plan_response_saves_behavior_fields_and_markdown(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "calculator.py").write_text(
                "def add(a, b):\n    return a + b\n",
                encoding="utf-8",
            )

            provider = _FakeProvider(
                json.dumps(
                    {
                        "summary": "Create a calculator CLI.",
                        "project_reading": "Python project with calculator functions.",
                        "files_involved": ["main.py", "calculator.py"],
                        "expected_behavior": [
                            "python main.py add 2 3 prints 5",
                            "python main.py divide 10 2 prints 5.0",
                        ],
                        "acceptance_criteria": [
                            "The CLI uses argparse.",
                            "Subcommands are registered before parse_args().",
                            "Runtime dispatch happens inside main().",
                        ],
                        "suggested_verification_commands": [
                            "python -m py_compile main.py calculator.py",
                            "python main.py add 2 3",
                        ],
                        "files_to_create": ["main.py"],
                        "files_to_modify": [],
                        "files_not_to_modify": ["calculator.py"],
                        "steps": ["Create main.py with argparse subcommands."],
                        "risks": ["Handle division by zero."],
                        "next_command": "trevvos diff",
                    }
                )
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    [
                        "plan",
                        "Crie uma CLI em main.py para executar as funcoes de calculator.py",
                        "--path",
                        str(root),
                    ],
                )

            self.assertEqual(result.exit_code, 0, result.output)

            session_dir = next((root / ".trevvos" / "sessions").iterdir())
            plan_json = json.loads((session_dir / "plan.json").read_text(encoding="utf-8"))
            plan_markdown = (session_dir / "plan.md").read_text(encoding="utf-8")

            self.assertEqual(plan_json["expected_behavior"][0], "python main.py add 2 3 prints 5")
            self.assertEqual(plan_json["files_to_create"], ["main.py"])
            self.assertEqual(plan_json["files_not_to_modify"], ["calculator.py"])
            self.assertIn("## Expected behavior", plan_markdown)
            self.assertIn("python main.py divide 10 2 prints 5.0", plan_markdown)
            self.assertIn("## Suggested commands to verify", plan_markdown)
            self.assertIn("python main.py add 2 3", plan_markdown)


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


if __name__ == "__main__":
    unittest.main()
