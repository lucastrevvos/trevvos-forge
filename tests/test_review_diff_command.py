import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.config_store import build_language_prompt_section
from trevvos_forge.prompt_catalog import get_prompt
from trevvos_forge.timeline import read_timeline


class ReviewDiffCommandTests(unittest.TestCase):
    def test_diff_review_prompt_contains_required_sections_and_rules(self) -> None:
        prompt = get_prompt("diff_review").render(
            diff_review_context="context",
            language_context=build_language_prompt_section("en"),
        )

        self.assertIn("Do not modify files", prompt)
        self.assertIn("Do not generate patches", prompt)
        self.assertIn("pull request review", prompt)
        self.assertIn("Risks and concerns", prompt)
        self.assertIn("Behavior preservation", prompt)
        self.assertIn("Tests to run", prompt)
        self.assertIn("Final recommendation", prompt)
        self.assertIn("request_changes", prompt)

    def test_review_diff_without_diff_does_not_call_provider(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _init_repo(root)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            _git(root, ["add", "main.py"])
            _git(root, ["commit", "-m", "initial"])

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["review-diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("No local diff found to review", result.output)
            build_provider.assert_not_called()
            self.assertFalse((root / ".trevvos" / "sessions").exists())

    def test_review_unstaged_diff_saves_advisory_artifacts(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _init_repo(root)
            main = root / "main.py"
            main.write_text("print('ok')\n", encoding="utf-8")
            _git(root, ["add", "main.py"])
            _git(root, ["commit", "-m", "initial"])
            main.write_text("print('changed')\n", encoding="utf-8")
            provider = _FakeProvider("# Diff Review\n\n## Final recommendation\n\nrequest_changes\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["review-diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(main.read_text(encoding="utf-8"), "print('changed')\n")
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "diff_review_metadata.json")

            self.assertTrue((session_dir / "diff_review.md").exists())
            self.assertTrue((session_dir / "diff_review_raw_response.md").exists())
            self.assertTrue((session_dir / "diff_review_prompt.md").exists())
            self.assertTrue((session_dir / "local_diff.patch").exists())
            self.assertTrue((session_dir / "git_status.txt").exists())
            self.assertTrue((session_dir / "diff_stat.txt").exists())
            self.assertTrue((session_dir / "context.md").exists())
            self.assertTrue((session_dir / "project_profile.json").exists())
            self.assertFalse(metadata["staged"])
            self.assertEqual(metadata["final_recommendation"], "request_changes")
            self.assertIn("main.py", metadata["files_changed"])
            self.assertFalse((session_dir / "file_changes.json").exists())
            self.assertFalse((session_dir / "apply_result.json").exists())

    def test_review_staged_diff_uses_cached_diff(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _init_repo(root)
            main = root / "main.py"
            main.write_text("print('ok')\n", encoding="utf-8")
            _git(root, ["add", "main.py"])
            _git(root, ["commit", "-m", "initial"])
            main.write_text("print('staged')\n", encoding="utf-8")
            _git(root, ["add", "main.py"])
            main.write_text("print('unstaged')\n", encoding="utf-8")
            provider = _FakeProvider("# Diff Review\n\n## Final recommendation\n\napprove_with_comments\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["review-diff", "--staged", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "diff_review_metadata.json")
            reviewed_diff = (session_dir / "local_diff.patch").read_text(encoding="utf-8")

            self.assertTrue(metadata["staged"])
            self.assertIn("print('staged')", reviewed_diff)
            self.assertNotIn("print('unstaged')", reviewed_diff)

    def test_review_diff_prompt_includes_profile_status_stat_and_diff(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _init_repo(root)
            main = root / "main.py"
            main.write_text("print('ok')\n", encoding="utf-8")
            _git(root, ["add", "main.py"])
            _git(root, ["commit", "-m", "initial"])
            main.write_text("print('changed')\n", encoding="utf-8")
            provider = _FakeProvider("# Diff Review\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["review-diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Project profile", provider.prompt)
            self.assertIn("# Git status", provider.prompt)
            self.assertIn("# Diff stat", provider.prompt)
            self.assertIn("# Diff", provider.prompt)
            self.assertIn("print('changed')", provider.prompt)

    def test_review_diff_json_outputs_metadata(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _init_repo(root)
            main = root / "main.py"
            main.write_text("print('ok')\n", encoding="utf-8")
            _git(root, ["add", "main.py"])
            _git(root, ["commit", "-m", "initial"])
            main.write_text("print('changed')\n", encoding="utf-8")
            provider = _FakeProvider("# Diff Review\n\n## Final recommendation\n\napprove\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["review-diff", "--json", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["command"], "review-diff")
            self.assertFalse(payload["staged"])
            self.assertEqual(payload["final_recommendation"], "approve")

    def test_review_diff_timeline_events(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _init_repo(root)
            main = root / "main.py"
            main.write_text("print('ok')\n", encoding="utf-8")
            _git(root, ["add", "main.py"])
            _git(root, ["commit", "-m", "initial"])
            main.write_text("print('changed')\n", encoding="utf-8")
            provider = _FakeProvider("# Diff Review\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["review-diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            events = [event["event"] for event in read_timeline(_only_session(root))]

            self.assertIn("review_diff_started", events)
            self.assertIn("review_diff_completed", events)

    def test_review_diff_help(self) -> None:
        result = CliRunner().invoke(app, ["review-diff", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--staged", result.output)
        self.assertIn("--json", result.output)


def _init_repo(root: Path) -> None:
    _git(root, ["init"])
    _git(root, ["config", "user.email", "test@example.com"])
    _git(root, ["config", "user.name", "Test User"])


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


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
