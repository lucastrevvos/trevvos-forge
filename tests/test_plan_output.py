import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.sessions import create_session
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

    def test_plan_saves_plan_error_for_invalid_json(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _FakeProvider("Aqui esta o plano:\n- faca X")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["plan", "Atualize o projeto", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            session_dir = next((root / ".trevvos" / "sessions").iterdir())
            plan_error = json.loads((session_dir / "plan_error.json").read_text(encoding="utf-8"))

            self.assertTrue((session_dir / "plan_error.md").exists())
            self.assertTrue((session_dir / "plan_raw_response.md").exists())
            self.assertEqual(plan_error["error_type"], "invalid_plan_json")
            self.assertEqual(plan_error["raw_response_path"], "plan_raw_response.md")
            self.assertIn("plan_error.json", result.output)
            self.assertFalse((session_dir / "plan.json").exists())

    def test_plan_retry_succeeds_from_plan_error(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            provider = _QueueProvider(
                [
                    "Aqui esta o plano:\n- faca X",
                    _valid_plan_response(),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                initial = runner.invoke(app, ["plan", "Atualize o projeto", "--path", str(root)])
                retry = runner.invoke(app, ["plan", "--retry", "--path", str(root)])

            self.assertEqual(initial.exit_code, 1, initial.output)
            self.assertEqual(retry.exit_code, 0, retry.output)
            session_dir = next((root / ".trevvos" / "sessions").iterdir())
            retry_metadata = json.loads((session_dir / "plan_retry_metadata.json").read_text(encoding="utf-8"))

            self.assertTrue((session_dir / "plan.json").exists())
            self.assertTrue((session_dir / "plan.md").exists())
            self.assertEqual(retry_metadata["status"], "succeeded")
            self.assertFalse((session_dir / "plan_error.json").exists())
            self.assertFalse((session_dir / "plan_error.md").exists())

    def test_plan_retry_fails_without_plan_error(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            create_session(root, "Atualize o projeto", command="plan")

            result = runner.invoke(app, ["plan", "--retry", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("No plan_error.json found for current session", result.output)


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


def _valid_plan_response() -> str:
    return json.dumps(
        {
            "summary": "Update project.",
            "project_reading": "Small project.",
            "files_involved": ["README.md"],
            "expected_behavior": ["README is updated."],
            "acceptance_criteria": ["README contains the requested text."],
            "suggested_verification_commands": [],
            "files_to_create": [],
            "files_to_modify": ["README.md"],
            "files_not_to_modify": [],
            "steps": ["Edit README.md."],
            "risks": [],
            "next_command": "trevvos diff",
        }
    )


if __name__ == "__main__":
    unittest.main()
