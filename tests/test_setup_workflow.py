"""Tests for setup_workflow.py — SetupRequest, SetupResult, run_setup()."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.exceptions import ConfigurationError
from trevvos_forge.setup_workflow import SetupRequest, SetupResult, run_setup

runner = CliRunner()


def _workspace(tmp: str) -> Path:
    root = Path(tmp)
    (root / ".trevvos").mkdir(parents=True, exist_ok=True)
    return root


def _mock_doctor(status: str = "passed") -> MagicMock:
    report = MagicMock()
    report.status = status
    report.has_failures = status == "failed"
    report.checks = [MagicMock()]
    return report


def _mock_profile(cmds: list[str] | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "suggested_test_commands": cmds or [],
        "suggested_build_commands": [],
        "languages": ["python"],
    }


# ---------------------------------------------------------------------------
# 1. Ollama non-interactive
# ---------------------------------------------------------------------------

class TestSetupOllamaNonInteractive(unittest.TestCase):
    def test_config_written_with_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                with patch("trevvos_forge.setup_workflow.scan_project", return_value=_mock_profile()):
                    with patch("trevvos_forge.setup_workflow.save_project_profile"):
                        result = run_setup(SetupRequest(
                            workspace_root=root,
                            provider="ollama",
                            model="qwen2.5-coder:7b",
                        ))
            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.provider, "ollama")
            self.assertEqual(result.runtime, "ollama")
            self.assertIsNotNone(result.config_path)
            cfg = json.loads(result.config_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
            self.assertEqual(cfg["provider"], "ollama")
            self.assertEqual(cfg["model"], "qwen2.5-coder:7b")
            self.assertNotIn("api_key", cfg)


# ---------------------------------------------------------------------------
# 2. OpenAI-compatible non-interactive
# ---------------------------------------------------------------------------

class TestSetupOpenAICompatible(unittest.TestCase):
    def test_config_written_openai_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                with patch("trevvos_forge.setup_workflow.scan_project", return_value=_mock_profile()):
                    with patch("trevvos_forge.setup_workflow.save_project_profile"):
                        result = run_setup(SetupRequest(
                            workspace_root=root,
                            provider="openai-compatible",
                            base_url="http://localhost:1234/v1",
                            model="qwen3-coder",
                        ))
            self.assertEqual(result.provider, "openai-compatible")
            self.assertEqual(result.runtime, "external")
            cfg = json.loads(result.config_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
            self.assertNotIn("api_key", cfg)
            self.assertEqual(cfg["runtime"], "external")


# ---------------------------------------------------------------------------
# 3. Existing config preserved
# ---------------------------------------------------------------------------

class TestExistingConfigPreserved(unittest.TestCase):
    def test_unrelated_keys_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            existing = {
                "language": "pt-BR",
                "test_commands": ["pytest"],
                "custom_key": "custom_value",
            }
            (root / ".trevvos" / "config.json").write_text(
                json.dumps(existing), encoding="utf-8"
            )
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                result = run_setup(SetupRequest(
                    workspace_root=root,
                    provider="ollama",
                    model="new-model",
                    run_inspect=False,
                ))
            cfg = json.loads(result.config_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
            self.assertEqual(cfg["custom_key"], "custom_value")
            self.assertEqual(cfg["language"], "pt-BR")
            self.assertEqual(cfg["model"], "new-model")
            self.assertEqual(cfg["provider"], "ollama")


# ---------------------------------------------------------------------------
# 4. Language normalization
# ---------------------------------------------------------------------------

class TestLanguageNormalization(unittest.TestCase):
    def test_pt_normalized_to_pt_br(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                result = run_setup(SetupRequest(
                    workspace_root=root,
                    provider="ollama",
                    language="pt",
                    run_inspect=False,
                ))
            self.assertEqual(result.language, "pt-BR")

    def test_en_us_normalized_to_en(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                result = run_setup(SetupRequest(
                    workspace_root=root,
                    provider="ollama",
                    language="en-us",
                    run_inspect=False,
                ))
            self.assertEqual(result.language, "en")


# ---------------------------------------------------------------------------
# 5. Test command detection — Python
# ---------------------------------------------------------------------------

class TestDetectTestCommandsPython(unittest.TestCase):
    def test_detects_unittest_discover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".trevvos").mkdir()
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_example.py").write_text(
                "import unittest\nclass T(unittest.TestCase): pass\n",
                encoding="utf-8",
            )
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                result = run_setup(SetupRequest(
                    workspace_root=root,
                    provider="ollama",
                    run_inspect=True,
                    run_doctor=False,
                ))
            self.assertTrue(
                any("unittest" in cmd for cmd in result.test_commands),
                f"Expected unittest command in {result.test_commands}",
            )


# ---------------------------------------------------------------------------
# 6. Test command detection — Node
# ---------------------------------------------------------------------------

class TestDetectTestCommandsNode(unittest.TestCase):
    def test_detects_npm_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".trevvos").mkdir()
            (root / "package.json").write_text(
                json.dumps({"name": "app", "scripts": {"test": "jest"}}),
                encoding="utf-8",
            )
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                result = run_setup(SetupRequest(
                    workspace_root=root,
                    provider="openai-compatible",
                    run_inspect=True,
                    run_doctor=False,
                ))
            self.assertIn("npm test", result.test_commands)


# ---------------------------------------------------------------------------
# 7. Test command detection — .NET
# ---------------------------------------------------------------------------

class TestDetectTestCommandsDotNet(unittest.TestCase):
    def test_detects_dotnet_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".trevvos").mkdir()
            (root / "MyApp.Tests.csproj").write_text(
                "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>",
                encoding="utf-8",
            )
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                result = run_setup(SetupRequest(
                    workspace_root=root,
                    provider="ollama",
                    run_inspect=True,
                    run_doctor=False,
                ))
            self.assertIn("dotnet test", result.test_commands)


# ---------------------------------------------------------------------------
# 8. Dry-run
# ---------------------------------------------------------------------------

class TestDryRun(unittest.TestCase):
    def test_no_config_file_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                result = run_setup(SetupRequest(
                    workspace_root=root,
                    provider="ollama",
                    run_inspect=False,
                    dry_run=True,
                ))
            self.assertIsNone(result.config_path)
            self.assertFalse((root / ".trevvos" / "config.json").exists())

    def test_cli_dry_run_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                result = runner.invoke(app, [
                    "setup",
                    "--provider", "ollama",
                    "--model", "test-model",
                    "--yes",
                    "--dry-run",
                    "--no-inspect",
                    "--path", tmp,
                ])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("dry-run", result.output)
            self.assertFalse((Path(tmp) / ".trevvos" / "config.json").exists())


# ---------------------------------------------------------------------------
# 9. JSON output
# ---------------------------------------------------------------------------

class TestJsonOutput(unittest.TestCase):
    def test_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(app, [
                "setup",
                "--provider", "ollama",
                "--model", "test-model",
                "--yes",
                "--json",
                "--no-doctor",
                "--no-inspect",
                "--path", tmp,
            ])
            self.assertEqual(result.exit_code, 0, result.output)
            data = json.loads(result.output.strip())
            self.assertEqual(data["status"], "succeeded")
            self.assertIn("provider", data)
            self.assertIn("duration_seconds", data)
            self.assertNotIn("api_key", data)

    def test_json_no_rich_wrapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(app, [
                "setup",
                "--provider", "openai-compatible",
                "--model", "gpt-4",
                "--yes",
                "--json",
                "--no-doctor",
                "--no-inspect",
                "--path", tmp,
            ])
            self.assertEqual(result.exit_code, 0, result.output)
            # Must be parseable as a single JSON object (no Rich newline insertion)
            data = json.loads(result.output.strip())
            self.assertEqual(data["provider"], "openai-compatible")


# ---------------------------------------------------------------------------
# 10. Doctor run mocked
# ---------------------------------------------------------------------------

class TestDoctorIntegration(unittest.TestCase):
    def test_doctor_called_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()) as mock_doc:
                run_setup(SetupRequest(
                    workspace_root=root,
                    provider="ollama",
                    run_inspect=False,
                    run_doctor=True,
                ))
            mock_doc.assert_called_once()

    def test_doctor_not_called_with_no_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with patch("trevvos_forge.setup_workflow._run_doctor") as mock_doc:
                result = run_setup(SetupRequest(
                    workspace_root=root,
                    provider="ollama",
                    run_inspect=False,
                    run_doctor=False,
                ))
            mock_doc.assert_not_called()
            self.assertIsNone(result.doctor)


# ---------------------------------------------------------------------------
# 11. Inspect / project profile
# ---------------------------------------------------------------------------

class TestInspectIntegration(unittest.TestCase):
    def test_profile_written_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            fake_profile = _mock_profile()
            with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                with patch("trevvos_forge.setup_workflow.scan_project", return_value=fake_profile):
                    with patch("trevvos_forge.setup_workflow.save_project_profile") as mock_save:
                        result = run_setup(SetupRequest(
                            workspace_root=root,
                            provider="ollama",
                            run_inspect=True,
                            run_doctor=False,
                        ))
            mock_save.assert_called_once()
            self.assertTrue(result.project_profile_written)

    def test_profile_not_written_with_no_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with patch("trevvos_forge.setup_workflow.scan_project") as mock_scan:
                with patch("trevvos_forge.setup_workflow.save_project_profile") as mock_save:
                    result = run_setup(SetupRequest(
                        workspace_root=root,
                        provider="ollama",
                        run_inspect=False,
                        run_doctor=False,
                    ))
            mock_scan.assert_not_called()
            mock_save.assert_not_called()
            self.assertFalse(result.project_profile_written)


# ---------------------------------------------------------------------------
# 12. CLI help
# ---------------------------------------------------------------------------

class TestCliHelp(unittest.TestCase):
    def test_setup_help(self) -> None:
        result = runner.invoke(app, ["setup", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--provider", result.output)
        self.assertIn("--model", result.output)
        self.assertIn("--yes", result.output)
        self.assertIn("--no-doctor", result.output)


# ---------------------------------------------------------------------------
# 13. Unknown provider error
# ---------------------------------------------------------------------------

class TestUnknownProvider(unittest.TestCase):
    def test_raises_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with self.assertRaises(ConfigurationError) as ctx:
                run_setup(SetupRequest(
                    workspace_root=root,
                    provider="unknown-provider",
                    run_inspect=False,
                    run_doctor=False,
                ))
            self.assertIn("unknown-provider", str(ctx.exception))

    def test_cli_exits_with_error(self) -> None:
        result = runner.invoke(app, [
            "setup",
            "--provider", "bad-provider",
            "--yes",
            "--no-doctor",
            "--no-inspect",
        ])
        self.assertNotEqual(result.exit_code, 0)


# ---------------------------------------------------------------------------
# 14. API key not leaked
# ---------------------------------------------------------------------------

class TestApiKeyNotLeaked(unittest.TestCase):
    def test_api_key_not_in_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _workspace(tmp)
            with patch.dict(os.environ, {"TREVVOS_FORGE_API_KEY": "sk-supersecret"}):
                with patch("trevvos_forge.setup_workflow._run_doctor", return_value=_mock_doctor()):
                    result = run_setup(SetupRequest(
                        workspace_root=root,
                        provider="openai-compatible",
                        run_inspect=False,
                        run_doctor=False,
                    ))
            cfg_text = result.config_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
            self.assertNotIn("sk-supersecret", cfg_text)
            self.assertNotIn("api_key", cfg_text)

    def test_api_key_not_in_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"TREVVOS_FORGE_API_KEY": "sk-supersecret"}):
                result = runner.invoke(app, [
                    "setup",
                    "--provider", "openai-compatible",
                    "--model", "gpt-4",
                    "--yes",
                    "--json",
                    "--no-doctor",
                    "--no-inspect",
                    "--path", tmp,
                ])
            self.assertNotIn("sk-supersecret", result.output)


if __name__ == "__main__":
    unittest.main()
