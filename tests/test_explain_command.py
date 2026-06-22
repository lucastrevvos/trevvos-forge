import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.config_store import build_language_prompt_section
from trevvos_forge.prompt_catalog import get_prompt
from trevvos_forge.timeline import read_timeline


class ExplainCommandTests(unittest.TestCase):
    def test_code_explanation_prompt_contains_required_sections_and_rules(self) -> None:
        prompt = get_prompt("code_explanation").render(
            explanation_context="context",
            language_context=build_language_prompt_section("en"),
        )

        self.assertIn("Do not modify files", prompt)
        self.assertIn("Do not generate patches", prompt)
        self.assertIn("Step-by-step walkthrough", prompt)
        self.assertIn("Execution flow", prompt)
        self.assertIn("Learning notes", prompt)
        self.assertIn("How to test it", prompt)
        self.assertIn("Separate facts from assumptions", prompt)

    def test_explain_file_saves_advisory_artifacts_without_modifying_tree(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            main = root / "main.py"
            main.write_text("def main():\n    print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Code Explanation\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["explain", "main.py", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(main.read_text(encoding="utf-8"), "def main():\n    print('ok')\n")
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "explanation_metadata.json")

            self.assertTrue((session_dir / "explanation.md").exists())
            self.assertTrue((session_dir / "explanation_prompt.md").exists())
            self.assertTrue((session_dir / "explanation_raw_response.md").exists())
            self.assertTrue((session_dir / "project_profile.json").exists())
            self.assertTrue((session_dir / "context.md").exists())
            self.assertEqual(metadata["mode"], "advisory")
            self.assertEqual(metadata["command"], "explain")
            self.assertEqual(metadata["files_explained"], ["main.py"])
            self.assertFalse((session_dir / "diff.patch").exists())
            self.assertFalse((session_dir / "file_changes.json").exists())
            self.assertFalse((session_dir / "apply_result.json").exists())

    def test_explain_existing_symbol(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "calculator.py").write_text(
                "def add(a, b):\n    return a + b\n\n"
                "def divide(a, b):\n    return a / b\n",
                encoding="utf-8",
            )
            provider = _FakeProvider("# Symbol Explanation\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["explain", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "explanation_metadata.json")

            self.assertEqual(metadata["symbol"], "divide")
            self.assertIn("divide", provider.prompt)
            self.assertIn("Symbol focus", provider.prompt)

    def test_explain_missing_symbol_fails_without_provider(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["explain", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Symbol `divide` not found in calculator.py", result.output)
            build_provider.assert_not_called()

    def test_explain_flow(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            (root / "main.py").write_text(
                "from calculator import add\n\n"
                "def main():\n"
                "    print(add(2, 3))\n\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n",
                encoding="utf-8",
            )
            provider = _FakeProvider("# Flow Explanation\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["explain", "main.py", "--flow", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "explanation_metadata.json")

            self.assertTrue(metadata["flow"])
            self.assertIn("Mode: flow", provider.prompt)
            self.assertIn("Related file: calculator.py", provider.prompt)

    def test_explain_includes_project_profile_and_line_numbers(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
            provider = _FakeProvider("# Code Explanation\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["explain", "main.py", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Project profile", provider.prompt)
            self.assertIn("1 | def main():", provider.prompt)

    def test_explain_timeline_events(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Code Explanation\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["explain", "main.py", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            events = [event["event"] for event in read_timeline(_only_session(root))]

            self.assertIn("explain_started", events)
            self.assertIn("explain_completed", events)

    def test_explain_json_flag_outputs_metadata(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Code Explanation\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["explain", "main.py", "--json", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["command"], "explain")
            self.assertEqual(payload["target"], "main.py")

    def test_explain_help(self) -> None:
        result = CliRunner().invoke(app, ["explain", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--symbol", result.output)
        self.assertIn("--flow", result.output)


def _only_session(root: Path) -> Path:
    return next((root / ".trevvos" / "sessions").iterdir())


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt = ""

    def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


if __name__ == "__main__":
    unittest.main()
