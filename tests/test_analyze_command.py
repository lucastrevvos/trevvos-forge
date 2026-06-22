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


class AnalyzeCommandTests(unittest.TestCase):
    def test_inspect_json_outputs_project_profile(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")

            result = runner.invoke(app, ["inspect", "--json", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertIn("python", payload["languages"])

    def test_analyze_file_saves_advisory_artifacts_without_modifying_tree(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            main = root / "main.py"
            main.write_text("def main():\n    print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Code Analysis\n\n## Executive summary\n\nLooks small.")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["analyze", "main.py", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(main.read_text(encoding="utf-8"), "def main():\n    print('ok')\n")
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "analysis_metadata.json")

            self.assertTrue((session_dir / "analysis_report.md").exists())
            self.assertTrue((session_dir / "project_profile.json").exists())
            self.assertTrue((session_dir / "selected_files.json").exists())
            self.assertEqual(metadata["mode"], "advisory")
            self.assertEqual(metadata["command"], "analyze")
            self.assertEqual(metadata["files_analyzed"], ["main.py"])
            self.assertFalse((session_dir / "diff.patch").exists())
            self.assertFalse((session_dir / "apply_result.json").exists())
            self.assertFalse((session_dir / "file_changes.json").exists())

    def test_code_analysis_prompt_contains_required_sections_and_rules(self) -> None:
        prompt = get_prompt("code_analysis").render(
            analysis_context="Project profile",
            language_context=build_language_prompt_section("en"),
        )

        self.assertIn("Do not generate patches", prompt)
        self.assertIn("Do not modify files", prompt)
        self.assertIn("## Executive summary", prompt)
        self.assertIn("## Risks and issues", prompt)
        self.assertIn("## Suggested tests", prompt)
        self.assertIn("## Learning notes", prompt)
        self.assertIn("## Suggested next steps", prompt)

    def test_analyze_prompt_contains_project_profile(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
            provider = _FakeProvider("# Code Analysis\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["analyze", "main.py", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Project profile", provider.prompt)
            self.assertIn("main.py", provider.prompt)
            self.assertIn("Content with line numbers", provider.prompt)

    def test_analyze_missing_file_fails_clearly(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            result = runner.invoke(app, ["analyze", "missing.py", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Analyze target does not exist", result.output)

    def test_analyze_timeline_events(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Code Analysis\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["analyze", "main.py", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            events = [event["event"] for event in read_timeline(_only_session(root))]

            self.assertIn("analyze_started", events)
            self.assertIn("analyze_completed", events)


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
