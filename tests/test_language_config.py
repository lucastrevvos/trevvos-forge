import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.exceptions import ConfigurationError
from trevvos_forge.config_store import normalize_language
from trevvos_forge.prompt_catalog import get_prompt


class LanguageConfigTests(unittest.TestCase):
    def test_normalize_language_aliases(self) -> None:
        self.assertEqual(normalize_language("pt"), "pt-BR")
        self.assertEqual(normalize_language("pt-BR"), "pt-BR")
        self.assertEqual(normalize_language("portuguese"), "pt-BR")
        self.assertEqual(normalize_language("en"), "en")
        self.assertEqual(normalize_language("en-US"), "en")

    def test_normalize_language_invalid_raises(self) -> None:
        with self.assertRaises(ConfigurationError):
            normalize_language("es")

    def test_config_set_and_show_language(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            result = runner.invoke(app, ["config", "set", "language", "pt-BR", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            config_path = root / ".trevvos" / "config.json"
            self.assertTrue(config_path.exists())
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["language"], "pt-BR")

            show = runner.invoke(app, ["config", "show", "--path", str(root)])
            self.assertEqual(show.exit_code, 0, show.output)
            self.assertIn("language: pt-BR", show.output)

    def test_config_set_invalid_language_fails(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            result = runner.invoke(app, ["config", "set", "language", "es", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Unsupported language", result.output)
            self.assertIn("Supported languages: en, pt-BR", result.output)

    def test_language_flag_overrides_config(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_dir = root / ".trevvos"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Code Analysis\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["analyze", "main.py", "--path", str(root), "--language", "pt-BR"],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(root)
            self.assertEqual(metadata["language"], "pt-BR")
            self.assertIn("Write the final report in Brazilian Portuguese (pt-BR).", provider.prompt)

    def test_analyze_default_language_is_en(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            provider = _FakeProvider("# Code Analysis\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["analyze", "main.py", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(root)
            self.assertEqual(metadata["language"], "en")
            self.assertIn("Write the final report in English.", provider.prompt)

    def test_explain_propose_spec_review_diff_receive_pt_br_language(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _git_init(root)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            _git(root, ["add", "main.py", "calculator.py"])
            _git(root, ["commit", "-m", "initial"])
            (root / "main.py").write_text("print('changed')\n", encoding="utf-8")
            provider = _FakeProvider("# Report\n")

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                runner.invoke(app, ["explain", "main.py", "--path", str(root), "--language", "pt-BR"])
                self.assertIn("Brazilian Portuguese (pt-BR)", provider.prompt)

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                runner.invoke(app, ["propose", "improve CLI", "--path", str(root), "--language", "pt-BR"])
                self.assertIn("Brazilian Portuguese (pt-BR)", provider.prompt)

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                runner.invoke(app, ["spec", "improve CLI", "--path", str(root), "--language", "pt-BR"])
                self.assertIn("Brazilian Portuguese (pt-BR)", provider.prompt)

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                runner.invoke(app, ["review-diff", "--path", str(root), "--language", "pt-BR"])
                self.assertIn("Brazilian Portuguese (pt-BR)", provider.prompt)

    def test_prompt_catalog_render_requires_language_context(self) -> None:
        prompt = get_prompt("code_analysis").render(
            analysis_context="context",
            language_context="Write the final report in English.",
        )

        self.assertIn("Write the final report in English.", prompt)

    def test_advisory_command_help_shows_language_option(self) -> None:
        runner = CliRunner()

        for command in [
            "analyze",
            "explain",
            "propose",
            "spec",
            "review-diff",
        ]:
            result = runner.invoke(app, [command, "--help"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("--language", result.output)


def _read_json(root: Path) -> dict:
    session_dir = next((root / ".trevvos" / "sessions").iterdir())
    payload = json.loads((session_dir / "analysis_metadata.json").read_text(encoding="utf-8"))
    return payload


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt = ""

    def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


def _git_init(root: Path) -> None:
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


if __name__ == "__main__":
    unittest.main()
