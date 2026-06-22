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


class SpecCommandTests(unittest.TestCase):
    def test_implementation_handoff_spec_prompt_contains_required_sections_and_rules(self) -> None:
        prompt = get_prompt("implementation_handoff_spec").render(
            handoff_context="Project profile",
            language_context=build_language_prompt_section("en"),
        )

        self.assertIn("Implementation Handoff Spec", prompt)
        self.assertIn("Copy-paste prompt", prompt)
        self.assertIn("Preserve existing behavior", prompt)
        self.assertIn("Acceptance criteria", prompt)
        self.assertIn("Verification commands", prompt)
        self.assertIn("Do not modify files directly", prompt)
        self.assertIn("Target AI", prompt)

    def test_spec_saves_advisory_artifacts_without_modifying_tree(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            main = root / "main.py"
            main.write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Implementation Handoff Spec\n\n## Copy-paste prompt\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["spec", "add sqrt", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(main.read_text(encoding="utf-8"), "print('ok')\n")
            session_dir = _only_session(root)

            self.assertTrue((session_dir / "handoff_spec.md").exists())
            self.assertTrue((session_dir / "external_ai_prompt.md").exists())
            self.assertTrue((session_dir / "handoff_metadata.json").exists())
            self.assertTrue((session_dir / "project_profile.json").exists())
            self.assertTrue((session_dir / "selected_files.json").exists())
            self.assertTrue((session_dir / "context.md").exists())
            self.assertFalse((session_dir / "diff.patch").exists())
            self.assertFalse((session_dir / "file_changes.json").exists())
            self.assertFalse((session_dir / "apply_result.json").exists())

    def test_spec_metadata(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Implementation Handoff Spec\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["spec", "add sqrt", "--target", "generic", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "handoff_metadata.json")

            self.assertEqual(metadata["mode"], "advisory")
            self.assertEqual(metadata["command"], "spec")
            self.assertEqual(metadata["target"], "generic")
            self.assertEqual(metadata["request"], "add sqrt")
            self.assertEqual(metadata["prompt"], "implementation_handoff_spec@1.0.0")
            self.assertEqual(metadata["status"], "succeeded")
            self.assertIn("main.py", metadata["files_included"])

    def test_spec_prompt_includes_project_profile_and_detected_commands(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text(
                "import argparse\n\n"
                "def main():\n"
                "    parser = argparse.ArgumentParser()\n"
                "    subparsers = parser.add_subparsers(dest='command')\n"
                "    subparsers.add_parser('add')\n\n"
                "if __name__ == '__main__':\n"
                "    main()\n",
                encoding="utf-8",
            )
            provider = _FakeProvider("# Implementation Handoff Spec\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["spec", "add sqrt", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Project profile", provider.prompt)
            self.assertIn("languages", provider.prompt)
            self.assertIn("entrypoints", provider.prompt)
            self.assertIn("add", provider.prompt)

    def test_spec_includes_relevant_files_for_python_project(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            (root / "main.py").write_text("from calculator import add\nprint(add(2, 3))\n", encoding="utf-8")
            provider = _FakeProvider("# Implementation Handoff Spec\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["spec", "add sqrt", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            selected = _read_json(_only_session(root) / "selected_files.json")

            self.assertIn("calculator.py", selected["files_included"])
            self.assertIn("main.py", selected["files_included"])
            self.assertIn("calculator.py", provider.prompt)
            self.assertIn("main.py", provider.prompt)

    def test_spec_json_outputs_metadata(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Implementation Handoff Spec\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["spec", "add sqrt", "--json", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["command"], "spec")
            self.assertEqual(payload["target"], "generic")
            self.assertIn("artifacts", payload)

    def test_spec_timeline_events(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Implementation Handoff Spec\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["spec", "add sqrt", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            events = [event["event"] for event in read_timeline(_only_session(root))]

            self.assertIn("spec_started", events)
            self.assertIn("spec_completed", events)

    def test_spec_empty_request_fails_clearly_without_provider(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["spec", "", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Spec request cannot be empty", result.output)
            build_provider.assert_not_called()

    def test_spec_help(self) -> None:
        result = CliRunner().invoke(app, ["spec", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--target", result.output)
        self.assertIn("--json", result.output)


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
