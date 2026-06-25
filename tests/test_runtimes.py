"""Unit tests for runtimes — ExternalRuntime, OllamaRuntime, factory, CLI."""
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.exceptions import RuntimeConfigurationError
from trevvos_forge.runtimes.base import RuntimeActionResult, RuntimeStatus
from trevvos_forge.runtimes.external import ExternalRuntime
from trevvos_forge.runtimes.factory import SUPPORTED_RUNTIMES, build_runtime_manager
from trevvos_forge.runtimes.ollama import OllamaRuntime

runner = CliRunner()


# ---------------------------------------------------------------------------
# Settings stub
# ---------------------------------------------------------------------------

@dataclass
class _Settings:
    provider: str = "ollama"
    model: str = "qwen2.5-coder:7b"
    base_url: str = "http://localhost:11434"
    timeout: int = 10
    api_key: str | None = None
    runtime: str | None = None


# ---------------------------------------------------------------------------
# RuntimeStatus / RuntimeActionResult
# ---------------------------------------------------------------------------

class TestRuntimeStatusToDict(unittest.TestCase):
    def test_is_running_true_included(self) -> None:
        s = RuntimeStatus(runtime="ollama", is_supported=True, is_running=True, base_url="http://x", message="ok")
        d = s.to_dict()
        self.assertTrue(d["is_running"])
        self.assertIn("base_url", d)

    def test_is_running_none_omitted(self) -> None:
        s = RuntimeStatus(runtime="external", is_supported=True, is_running=None, base_url=None, message="external")
        d = s.to_dict()
        self.assertNotIn("is_running", d)
        self.assertNotIn("base_url", d)

    def test_details_omitted_when_none(self) -> None:
        s = RuntimeStatus(runtime="ollama", is_supported=True, is_running=True, base_url=None, message="ok")
        d = s.to_dict()
        self.assertNotIn("details", d)


class TestRuntimeActionResultToDict(unittest.TestCase):
    def test_basic_fields(self) -> None:
        r = RuntimeActionResult(runtime="ollama", action="start", status="succeeded", message="ok")
        d = r.to_dict()
        self.assertEqual(d["runtime"], "ollama")
        self.assertEqual(d["action"], "start")
        self.assertEqual(d["status"], "succeeded")

    def test_details_omitted_when_none(self) -> None:
        r = RuntimeActionResult(runtime="ollama", action="stop", status="skipped", message="ok")
        d = r.to_dict()
        self.assertNotIn("details", d)

    def test_details_included_when_present(self) -> None:
        r = RuntimeActionResult(runtime="ollama", action="start", status="succeeded", message="ok", details={"pid": 123})
        d = r.to_dict()
        self.assertEqual(d["details"]["pid"], 123)


# ---------------------------------------------------------------------------
# ExternalRuntime
# ---------------------------------------------------------------------------

class TestExternalRuntime(unittest.TestCase):
    def test_status_is_supported_and_is_running_none(self) -> None:
        rt = ExternalRuntime(base_url="https://api.openai.com/v1")
        s = rt.status()
        self.assertEqual(s.runtime, "external")
        self.assertTrue(s.is_supported)
        self.assertIsNone(s.is_running)

    def test_status_base_url_preserved(self) -> None:
        rt = ExternalRuntime(base_url="http://x:1234/v1")
        s = rt.status()
        self.assertEqual(s.base_url, "http://x:1234/v1")

    def test_start_is_unsupported(self) -> None:
        rt = ExternalRuntime()
        r = rt.start()
        self.assertEqual(r.status, "unsupported")
        self.assertEqual(r.action, "start")

    def test_stop_is_unsupported(self) -> None:
        rt = ExternalRuntime()
        r = rt.stop()
        self.assertEqual(r.status, "unsupported")
        self.assertEqual(r.action, "stop")

    def test_status_to_dict_omits_is_running(self) -> None:
        rt = ExternalRuntime()
        d = rt.status().to_dict()
        self.assertNotIn("is_running", d)


# ---------------------------------------------------------------------------
# OllamaRuntime — status
# ---------------------------------------------------------------------------

class TestOllamaRuntimeStatus(unittest.TestCase):
    @patch("trevvos_forge.runtimes.ollama.requests.get")
    def test_running_when_200(self, mock_get: MagicMock) -> None:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp
        rt = OllamaRuntime(base_url="http://localhost:11434")
        s = rt.status()
        self.assertEqual(s.runtime, "ollama")
        self.assertTrue(s.is_running)
        self.assertTrue(s.is_supported)

    @patch("trevvos_forge.runtimes.ollama.requests.get")
    def test_not_running_on_connection_error(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        rt = OllamaRuntime(base_url="http://localhost:11434")
        s = rt.status()
        self.assertFalse(s.is_running)
        self.assertIn("not running", s.message)

    @patch("trevvos_forge.runtimes.ollama.requests.get")
    def test_unknown_on_timeout(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.exceptions.Timeout("timed out")
        rt = OllamaRuntime()
        s = rt.status()
        self.assertIsNone(s.is_running)
        self.assertIn("timed out", s.message)

    @patch("trevvos_forge.runtimes.ollama.requests.get")
    def test_base_url_in_status(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.exceptions.ConnectionError()
        rt = OllamaRuntime(base_url="http://localhost:11434")
        s = rt.status()
        self.assertEqual(s.base_url, "http://localhost:11434")


# ---------------------------------------------------------------------------
# OllamaRuntime — start
# ---------------------------------------------------------------------------

class TestOllamaRuntimeStart(unittest.TestCase):
    @patch("trevvos_forge.runtimes.ollama.OllamaRuntime._check_running")
    def test_already_running_returns_skipped(self, mock_check: MagicMock) -> None:
        mock_check.return_value = True
        rt = OllamaRuntime()
        r = rt.start()
        self.assertEqual(r.status, "skipped")
        self.assertIn("already running", r.message)
        self.assertEqual(r.action, "start")

    @patch("trevvos_forge.runtimes.ollama.shutil.which")
    @patch("trevvos_forge.runtimes.ollama.OllamaRuntime._check_running")
    def test_missing_executable_fails(self, mock_check: MagicMock, mock_which: MagicMock) -> None:
        mock_check.return_value = False
        mock_which.return_value = None
        rt = OllamaRuntime()
        r = rt.start()
        self.assertEqual(r.status, "failed")
        self.assertIn("not found", r.message.lower())

    @patch("trevvos_forge.runtimes.ollama.time.sleep")
    @patch("trevvos_forge.runtimes.ollama.subprocess.Popen")
    @patch("trevvos_forge.runtimes.ollama.shutil.which")
    @patch("trevvos_forge.runtimes.ollama.OllamaRuntime._check_running")
    def test_start_success_saves_state(
        self,
        mock_check: MagicMock,
        mock_which: MagicMock,
        mock_popen: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        # First call: not running; second call (inside poll loop): running
        mock_check.side_effect = [False, True]
        mock_which.return_value = "/usr/bin/ollama"
        fake_proc = MagicMock()
        fake_proc.pid = 99999
        mock_popen.return_value = fake_proc

        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            rt = OllamaRuntime(workspace_root=workspace_root)
            r = rt.start()

        self.assertEqual(r.status, "succeeded")
        self.assertIn("started", r.message.lower())
        self.assertEqual(r.details["pid"], 99999)

    @patch("trevvos_forge.runtimes.ollama.time.sleep")
    @patch("trevvos_forge.runtimes.ollama.subprocess.Popen")
    @patch("trevvos_forge.runtimes.ollama.shutil.which")
    @patch("trevvos_forge.runtimes.ollama.OllamaRuntime._check_running")
    def test_start_saves_runtime_state_json(
        self,
        mock_check: MagicMock,
        mock_which: MagicMock,
        mock_popen: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        mock_check.side_effect = [False, True]
        mock_which.return_value = "/usr/bin/ollama"
        fake_proc = MagicMock()
        fake_proc.pid = 42
        mock_popen.return_value = fake_proc

        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            rt = OllamaRuntime(workspace_root=workspace_root)
            rt.start()
            state_file = workspace_root / ".trevvos" / "runtime_state.json"
            self.assertTrue(state_file.exists())
            state = json.loads(state_file.read_text())
            self.assertEqual(state["pid"], 42)
            self.assertTrue(state["managed_by_forge"])
            self.assertEqual(state["runtime"], "ollama")

    @patch("trevvos_forge.runtimes.ollama.time.time")
    @patch("trevvos_forge.runtimes.ollama.time.sleep")
    @patch("trevvos_forge.runtimes.ollama.subprocess.Popen")
    @patch("trevvos_forge.runtimes.ollama.shutil.which")
    @patch("trevvos_forge.runtimes.ollama.OllamaRuntime._check_running")
    def test_start_failure_never_reachable(
        self,
        mock_check: MagicMock,
        mock_which: MagicMock,
        mock_popen: MagicMock,
        mock_sleep: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        # Always returns False (never reachable)
        mock_check.return_value = False
        mock_which.return_value = "/usr/bin/ollama"
        fake_proc = MagicMock()
        fake_proc.pid = 9999
        mock_popen.return_value = fake_proc
        # Make time.time() immediately exceed deadline
        mock_time.side_effect = [0.0, 100.0]  # start, first check already past deadline

        rt = OllamaRuntime()
        r = rt.start()
        self.assertEqual(r.status, "failed")


# ---------------------------------------------------------------------------
# OllamaRuntime — stop
# ---------------------------------------------------------------------------

class TestOllamaRuntimeStop(unittest.TestCase):
    def test_stop_unmanaged_no_state_returns_skipped(self) -> None:
        rt = OllamaRuntime()  # no workspace_root → no state file
        r = rt.stop()
        self.assertEqual(r.status, "skipped")
        self.assertIn("Forge", r.message)
        self.assertEqual(r.action, "stop")

    def test_stop_unmanaged_with_state_false_returns_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            state_file = workspace_root / ".trevvos" / "runtime_state.json"
            state_file.parent.mkdir(parents=True)
            state_file.write_text(json.dumps({"runtime": "ollama", "managed_by_forge": False, "pid": 1234}))
            rt = OllamaRuntime(workspace_root=workspace_root)
            r = rt.stop()
        self.assertEqual(r.status, "skipped")

    @patch("trevvos_forge.runtimes.ollama.os.kill")
    def test_stop_managed_calls_kill_and_clears_state(self, mock_kill: MagicMock) -> None:
        mock_kill.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            state_file = workspace_root / ".trevvos" / "runtime_state.json"
            state_file.parent.mkdir(parents=True)
            state_file.write_text(json.dumps({
                "runtime": "ollama",
                "managed_by_forge": True,
                "pid": 55555,
            }))
            rt = OllamaRuntime(workspace_root=workspace_root)
            r = rt.stop()
            self.assertEqual(r.status, "succeeded")
            self.assertEqual(r.details["pid"], 55555)
            mock_kill.assert_called_once()
            self.assertFalse(state_file.exists())

    @patch("trevvos_forge.runtimes.ollama.os.kill")
    def test_stop_process_already_gone_returns_skipped(self, mock_kill: MagicMock) -> None:
        mock_kill.side_effect = ProcessLookupError(3, "No such process")
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            state_file = workspace_root / ".trevvos" / "runtime_state.json"
            state_file.parent.mkdir(parents=True)
            state_file.write_text(json.dumps({"runtime": "ollama", "managed_by_forge": True, "pid": 1}))
            rt = OllamaRuntime(workspace_root=workspace_root)
            r = rt.stop()
        self.assertEqual(r.status, "skipped")
        self.assertFalse(state_file.exists())


# ---------------------------------------------------------------------------
# Runtime factory
# ---------------------------------------------------------------------------

class TestRuntimeFactory(unittest.TestCase):
    def test_provider_ollama_defaults_to_ollama_runtime(self) -> None:
        settings = _Settings(provider="ollama")
        rt = build_runtime_manager(settings)
        self.assertIsInstance(rt, OllamaRuntime)

    def test_provider_openai_compatible_defaults_to_external(self) -> None:
        settings = _Settings(provider="openai-compatible")
        rt = build_runtime_manager(settings)
        self.assertIsInstance(rt, ExternalRuntime)

    def test_explicit_runtime_overrides_provider_default(self) -> None:
        settings = _Settings(provider="ollama", runtime="external")
        rt = build_runtime_manager(settings)
        self.assertIsInstance(rt, ExternalRuntime)

    def test_explicit_external_runtime(self) -> None:
        settings = _Settings(provider="openai-compatible", runtime="external")
        rt = build_runtime_manager(settings)
        self.assertIsInstance(rt, ExternalRuntime)

    def test_unknown_runtime_raises_error(self) -> None:
        settings = _Settings(runtime="unknown-runtime")
        with self.assertRaises(RuntimeConfigurationError) as cm:
            build_runtime_manager(settings)
        self.assertIn("unknown-runtime", str(cm.exception))
        self.assertIn("ollama", str(cm.exception))

    def test_workspace_root_passed_to_ollama(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = _Settings(provider="ollama")
            rt = build_runtime_manager(settings, workspace_root=Path(tmp))
            self.assertIsInstance(rt, OllamaRuntime)
            self.assertEqual(rt.workspace_root, Path(tmp))

    def test_supported_runtimes_tuple(self) -> None:
        self.assertIn("ollama", SUPPORTED_RUNTIMES)
        self.assertIn("external", SUPPORTED_RUNTIMES)


# ---------------------------------------------------------------------------
# CLI runtime commands
# ---------------------------------------------------------------------------

class TestRuntimeCLI(unittest.TestCase):
    @patch("trevvos_forge.cli.build_runtime_manager")
    def test_runtime_status_human_output(self, mock_build: MagicMock) -> None:
        mock_rt = MagicMock()
        mock_rt.status.return_value = RuntimeStatus(
            runtime="ollama",
            is_supported=True,
            is_running=True,
            base_url="http://localhost:11434",
            message="Ollama runtime is reachable.",
        )
        mock_build.return_value = mock_rt
        result = runner.invoke(app, ["runtime", "status"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Runtime", result.output)
        self.assertIn("Duration:", result.output)

    @patch("trevvos_forge.cli.build_runtime_manager")
    def test_runtime_status_json_output(self, mock_build: MagicMock) -> None:
        mock_rt = MagicMock()
        mock_rt.status.return_value = RuntimeStatus(
            runtime="ollama",
            is_supported=True,
            is_running=True,
            base_url="http://localhost:11434",
            message="Ollama runtime is reachable.",
        )
        mock_build.return_value = mock_rt
        result = runner.invoke(app, ["runtime", "status", "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output.strip())
        self.assertIn("runtime", data)
        self.assertIn("duration_seconds", data)
        self.assertEqual(data["action"], "status")

    @patch("trevvos_forge.cli.build_runtime_manager")
    def test_runtime_start_human_output(self, mock_build: MagicMock) -> None:
        mock_rt = MagicMock()
        mock_rt.start.return_value = RuntimeActionResult(
            runtime="ollama",
            action="start",
            status="skipped",
            message="Ollama runtime is already running.",
        )
        mock_build.return_value = mock_rt
        result = runner.invoke(app, ["runtime", "start"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Runtime start", result.output)
        self.assertIn("Duration:", result.output)

    @patch("trevvos_forge.cli.build_runtime_manager")
    def test_runtime_start_json_output(self, mock_build: MagicMock) -> None:
        mock_rt = MagicMock()
        mock_rt.start.return_value = RuntimeActionResult(
            runtime="ollama",
            action="start",
            status="succeeded",
            message="Ollama started.",
            details={"pid": 123},
        )
        mock_build.return_value = mock_rt
        result = runner.invoke(app, ["runtime", "start", "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output.strip())
        self.assertIn("duration_seconds", data)
        self.assertEqual(data["status"], "succeeded")

    @patch("trevvos_forge.cli.build_runtime_manager")
    def test_runtime_stop_human_output(self, mock_build: MagicMock) -> None:
        mock_rt = MagicMock()
        mock_rt.stop.return_value = RuntimeActionResult(
            runtime="ollama",
            action="stop",
            status="skipped",
            message="Not started by Trevvos Forge.",
        )
        mock_build.return_value = mock_rt
        result = runner.invoke(app, ["runtime", "stop"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Duration:", result.output)

    @patch("trevvos_forge.cli.build_runtime_manager")
    def test_runtime_start_failed_exits_1(self, mock_build: MagicMock) -> None:
        mock_rt = MagicMock()
        mock_rt.start.return_value = RuntimeActionResult(
            runtime="ollama",
            action="start",
            status="failed",
            message="Ollama executable not found.",
        )
        mock_build.return_value = mock_rt
        result = runner.invoke(app, ["runtime", "start"])
        self.assertEqual(result.exit_code, 1)

    @patch("trevvos_forge.cli.build_runtime_manager")
    def test_runtime_stop_failed_exits_1(self, mock_build: MagicMock) -> None:
        mock_rt = MagicMock()
        mock_rt.stop.return_value = RuntimeActionResult(
            runtime="ollama",
            action="stop",
            status="failed",
            message="Permission denied.",
        )
        mock_build.return_value = mock_rt
        result = runner.invoke(app, ["runtime", "stop"])
        self.assertEqual(result.exit_code, 1)

    def test_runtime_status_help(self) -> None:
        result = runner.invoke(app, ["runtime", "status", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--json", result.output)

    def test_runtime_start_help(self) -> None:
        result = runner.invoke(app, ["runtime", "start", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--json", result.output)

    def test_runtime_stop_help(self) -> None:
        result = runner.invoke(app, ["runtime", "stop", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--json", result.output)


if __name__ == "__main__":
    unittest.main()
