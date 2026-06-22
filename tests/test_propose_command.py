import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.prompt_catalog import get_prompt
from trevvos_forge.timeline import read_timeline


class ProposeCommandTests(unittest.TestCase):
    def test_technical_proposal_prompt_contains_required_sections_and_rules(self) -> None:
        prompt = get_prompt("technical_proposal").render(proposal_context="Project profile")

        self.assertIn("Do not modify files", prompt)
        self.assertIn("Do not generate patches", prompt)
        self.assertIn("Technical Proposal", prompt)
        self.assertIn("Recommended approach", prompt)
        self.assertIn("Alternatives considered", prompt)
        self.assertIn("Proposed implementation plan", prompt)
        self.assertIn("Acceptance criteria", prompt)
        self.assertIn("Verification plan", prompt)
        self.assertIn("Risks and edge cases", prompt)
        self.assertIn("Suggested next steps", prompt)

    def test_propose_saves_advisory_artifacts_without_modifying_tree(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            main = root / "main.py"
            main.write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Technical Proposal\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["propose", "improve CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(main.read_text(encoding="utf-8"), "print('ok')\n")
            session_dir = _only_session(root)

            self.assertTrue((session_dir / "proposal.md").exists())
            self.assertTrue((session_dir / "proposal_metadata.json").exists())
            self.assertTrue((session_dir / "proposal_prompt.md").exists())
            self.assertTrue((session_dir / "proposal_raw_response.md").exists())
            self.assertTrue((session_dir / "project_profile.json").exists())
            self.assertTrue((session_dir / "selected_files.json").exists())
            self.assertTrue((session_dir / "context.md").exists())
            self.assertFalse((session_dir / "diff.patch").exists())
            self.assertFalse((session_dir / "file_changes.json").exists())
            self.assertFalse((session_dir / "apply_result.json").exists())

    def test_propose_metadata(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Technical Proposal\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["propose", "add auth", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "proposal_metadata.json")

            self.assertEqual(metadata["mode"], "advisory")
            self.assertEqual(metadata["command"], "propose")
            self.assertEqual(metadata["request"], "add auth")
            self.assertIsNone(metadata["target"])
            self.assertEqual(metadata["prompt"], "technical_proposal@1.0.0")
            self.assertEqual(metadata["status"], "succeeded")
            self.assertIn("main.py", metadata["files_considered"])

    def test_propose_prompt_includes_project_profile_and_request(self) -> None:
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
            provider = _FakeProvider("# Technical Proposal\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["propose", "melhorar a CLI", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Project profile", provider.prompt)
            self.assertIn("languages", provider.prompt)
            self.assertIn("entrypoints", provider.prompt)
            self.assertIn("add", provider.prompt)
            self.assertIn("melhorar a CLI", provider.prompt)

    def test_propose_existing_target_prioritizes_target_files(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            src = root / "src"
            src.mkdir()
            (src / "domain.py").write_text("class Money:\n    pass\n", encoding="utf-8")
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Technical Proposal\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["propose", "melhorar esse módulo", "--target", "src", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "proposal_metadata.json")

            self.assertEqual(metadata["target"], "src")
            self.assertEqual(metadata["files_considered"], ["src/domain.py"])
            self.assertIn("src/domain.py", provider.prompt)

    def test_propose_missing_target_fails_without_provider(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["propose", "melhorar", "--target", "missing", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Target path not found", result.output)
            build_provider.assert_not_called()

    def test_propose_json_outputs_metadata(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Technical Proposal\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["propose", "add auth", "--json", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["command"], "propose")
            self.assertEqual(payload["request"], "add auth")
            self.assertIn("artifacts", payload)

    def test_propose_timeline_events(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Technical Proposal\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["propose", "add auth", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            events = [event["event"] for event in read_timeline(_only_session(root))]

            self.assertIn("propose_started", events)
            self.assertIn("propose_completed", events)

    def test_propose_help(self) -> None:
        result = CliRunner().invoke(app, ["propose", "--help"])

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
