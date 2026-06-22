import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.repair_workflow import build_repair_context, build_repair_prompt
from trevvos_forge.sessions import create_session, write_session_json, write_session_text


class CliRegressionIntegrationTests(unittest.TestCase):
    def test_diff_saves_cli_regression_check(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_cli(root / "main.py")
            session = _create_diff_session(root)
            provider = _FakeProvider(_remove_divide_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            payload = _read_json(session.path / "cli_regression_check.json")
            semantic = _read_json(session.path / "semantic_review.json")

            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["checks"][0]["removed_subcommands"], ["divide"])
            self.assertIn("Existing CLI command 'divide' appears to have been removed.", semantic["concerns"])

    def test_work_blocks_ready_to_apply_on_cli_regression(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_cli(root / "main.py")
            provider = _QueueProvider(
                [
                    _plan_response(),
                    _remove_divide_response(),
                ]
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["work", "Add sqrt", "--path", str(root), "--max-repairs", "0"],
                )

            self.assertEqual(result.exit_code, 1)
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "work_metadata.json")
            cli_check = _read_json(session_dir / "cli_regression_check.json")

            self.assertEqual(metadata["status"], "blocked")
            self.assertEqual(metadata["final_phase"], "cli_regression_failed")
            self.assertEqual(cli_check["status"], "failed")

    def test_repair_prompt_includes_cli_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_cli(root / "main.py")
            session = create_session(root, "Add sqrt", command="plan")
            write_session_json(
                session,
                "plan.json",
                {
                    "files_to_modify": ["main.py"],
                    "acceptance_criteria": ["Preserve existing commands"],
                    "suggested_verification_commands": ["python main.py divide 10 2"],
                },
            )
            write_session_text(session, "plan.md", "Plan.")
            write_session_json(
                session,
                "file_changes.json",
                {"changes": [{"path": "main.py", "change_type": "modified", "mode": "full_file_rewrite"}]},
            )
            write_session_text(session, "diff.patch", "diff --git a/main.py b/main.py\n")
            write_session_json(
                session,
                "cli_regression_check.json",
                {
                    "status": "failed",
                    "checks": [
                        {
                            "path": "main.py",
                            "removed_subcommands": ["divide"],
                            "removed_dispatch_commands": ["divide"],
                        }
                    ],
                    "warnings": ["Existing CLI command 'divide' appears to have been removed."],
                },
            )

            prompt = build_repair_prompt(build_repair_context(session=session, repo_root=root))

            self.assertIn("CLI regression detected", prompt)
            self.assertIn("Existing command divide was removed", prompt)
            self.assertIn("preserve all existing CLI commands", prompt)
            self.assertIn("add the new command without replacing", prompt)


def _write_cli(path: Path) -> None:
    path.write_text(
        "import argparse\n\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    subparsers = parser.add_subparsers(dest='command')\n"
        "    subparsers.add_parser(\"add\")\n"
        "    subparsers.add_parser(\"divide\")\n"
        "    args = parser.parse_args()\n"
        "    if args.command == \"add\":\n"
        "        print('add')\n"
        "    elif args.command == \"divide\":\n"
        "        print('divide')\n\n"
        "if __name__ == \"__main__\":\n"
        "    main()\n",
        encoding="utf-8",
    )


def _create_diff_session(root: Path):
    session = create_session(root, "Add sqrt", command="plan")
    write_session_text(session, "context.md", "context")
    write_session_text(session, "plan.md", "plan")
    write_session_json(
        session,
        "plan.json",
        {
            "files_to_modify": ["main.py"],
            "expected_behavior": ["python main.py sqrt 9 prints 3.0"],
            "acceptance_criteria": ["Preserve existing commands"],
            "suggested_verification_commands": [f'"{sys.executable}" main.py sqrt 9'],
        },
    )
    write_session_json(
        session,
        "verification_coverage.json",
        {"status": "passed", "missing": [], "warnings": []},
    )
    write_session_json(
        session,
        "selected_files.json",
        {
            "selected_files": [
                {
                    "path": "main.py",
                    "total_lines": 14,
                    "included_ranges": [{"start_line": 1, "end_line": 14}],
                }
            ]
        },
    )
    return session


def _plan_response() -> str:
    return json.dumps(
        {
            "summary": "Add sqrt.",
            "project_reading": "Python CLI.",
            "files_involved": ["main.py"],
            "expected_behavior": ["python main.py sqrt 9 prints 3.0"],
            "acceptance_criteria": ["sqrt is added without removing existing add and divide commands"],
            "suggested_verification_commands": [f'"{sys.executable}" main.py sqrt 9'],
            "files_to_create": [],
            "files_to_modify": ["main.py"],
            "files_not_to_modify": [],
            "steps": ["Update CLI."],
            "risks": [],
            "next_command": "trevvos diff",
        }
    )


def _remove_divide_response() -> str:
    new_content = (
        "import argparse\n\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    subparsers = parser.add_subparsers(dest='command')\n"
        "    subparsers.add_parser(\"add\")\n"
        "    subparsers.add_parser(\"sqrt\")\n"
        "    args = parser.parse_args()\n"
        "    if args.command == \"add\":\n"
        "        print('add')\n"
        "    elif args.command == \"sqrt\":\n"
        "        print('sqrt')\n\n"
        "if __name__ == \"__main__\":\n"
        "    main()\n"
    )
    return json.dumps(
        {
            "changes": [
                {
                    "path": "main.py",
                    "change_type": "modified",
                    "mode": "full_file_rewrite",
                    "content": new_content,
                }
            ]
        }
    )


def _only_session(root: Path) -> Path:
    return next((root / ".trevvos" / "sessions").iterdir())


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
