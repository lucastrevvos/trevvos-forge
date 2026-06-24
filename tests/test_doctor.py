"""Unit tests for doctor.py — runtime detection and provider health checks."""
import json
import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.doctor import (
    DoctorCheck,
    DoctorReport,
    run_doctor,
    run_ollama_doctor,
    run_openai_compatible_doctor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _Settings:
    provider: str = "ollama"
    model: str = "qwen2.5-coder:7b"
    base_url: str = "http://localhost:11434"
    timeout: int = 30
    api_key: str | None = None


def _fake_get_response(status_code: int, json_body: Any) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    if status_code >= 400:
        import requests
        http_err = requests.exceptions.HTTPError(response=resp)
        resp.raise_for_status.side_effect = http_err
    else:
        resp.raise_for_status.return_value = None
    return resp


def _fake_post_response(status_code: int, json_body: Any) -> MagicMock:
    return _fake_get_response(status_code, json_body)


runner = CliRunner()


# ---------------------------------------------------------------------------
# DoctorCheck / DoctorReport unit tests
# ---------------------------------------------------------------------------

class TestDoctorCheckToDict(unittest.TestCase):
    def test_to_dict_minimal(self) -> None:
        c = DoctorCheck(name="config_loaded", status="passed", message="ok")
        d = c.to_dict()
        self.assertEqual(d["name"], "config_loaded")
        self.assertEqual(d["status"], "passed")
        self.assertEqual(d["message"], "ok")
        self.assertNotIn("duration_seconds", d)
        self.assertNotIn("details", d)

    def test_to_dict_with_duration(self) -> None:
        c = DoctorCheck(name="check", status="passed", message="ok", duration_seconds=0.12)
        d = c.to_dict()
        self.assertEqual(d["duration_seconds"], 0.12)

    def test_to_dict_with_details(self) -> None:
        c = DoctorCheck(name="check", status="warning", message="warn", details={"key": "val"})
        d = c.to_dict()
        self.assertEqual(d["details"], {"key": "val"})


class TestDoctorReport(unittest.TestCase):
    def _report(self, *statuses: str) -> DoctorReport:
        checks = [DoctorCheck(name=f"c{i}", status=s, message=s) for i, s in enumerate(statuses)]
        return DoctorReport(
            provider="ollama", model="m", base_url="http://x", checks=checks, duration_seconds=0.1
        )

    def test_status_passed_when_all_passed(self) -> None:
        self.assertEqual(self._report("passed", "passed").status, "passed")

    def test_status_failed_when_any_failed(self) -> None:
        self.assertEqual(self._report("passed", "failed").status, "failed")

    def test_status_warning_when_only_warnings(self) -> None:
        self.assertEqual(self._report("passed", "warning").status, "warning")

    def test_has_failures_true(self) -> None:
        self.assertTrue(self._report("failed").has_failures)

    def test_has_failures_false(self) -> None:
        self.assertFalse(self._report("passed", "warning").has_failures)

    def test_to_dict_masks_api_key_present(self) -> None:
        report = DoctorReport(
            provider="openai-compatible", model="m", base_url="http://x",
            checks=[], duration_seconds=0.1, api_key_present=True,
        )
        d = report.to_dict()
        self.assertEqual(d["api_key"], "present")
        self.assertNotIn("sk-", str(d))

    def test_to_dict_api_key_absent(self) -> None:
        report = DoctorReport(
            provider="openai-compatible", model="m", base_url="http://x",
            checks=[], duration_seconds=0.1, api_key_present=False,
        )
        d = report.to_dict()
        self.assertEqual(d["api_key"], "not set")

    def test_to_dict_contains_all_fields(self) -> None:
        report = self._report("passed")
        d = report.to_dict()
        for key in ("provider", "model", "base_url", "api_key", "status", "duration_seconds", "checks"):
            self.assertIn(key, d)


# ---------------------------------------------------------------------------
# Ollama doctor
# ---------------------------------------------------------------------------

class TestOllamaDoctor(unittest.TestCase):
    def _settings(self, model: str = "qwen2.5-coder:7b") -> _Settings:
        return _Settings(provider="ollama", model=model, base_url="http://localhost:11434", timeout=30)

    @patch("trevvos_forge.doctor.requests.get")
    def test_runtime_reachable_model_found(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {
            "models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3"}]
        })
        report = run_ollama_doctor(self._settings())
        self.assertEqual(report.provider, "ollama")
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["runtime_reachable"], "passed")
        self.assertEqual(names["model_present"], "passed")
        self.assertFalse(report.has_failures)

    @patch("trevvos_forge.doctor.requests.get")
    def test_runtime_reachable_model_missing_warns(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {
            "models": [{"name": "llama3"}]
        })
        report = run_ollama_doctor(self._settings("missing-model"))
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["runtime_reachable"], "passed")
        self.assertEqual(names["model_present"], "warning")
        self.assertFalse(report.has_failures)

    @patch("trevvos_forge.doctor.requests.get")
    def test_connection_error_fails_runtime(self, mock_get: MagicMock) -> None:
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("refused")
        report = run_ollama_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["runtime_reachable"], "failed")
        self.assertEqual(names["model_present"], "skipped")
        self.assertTrue(report.has_failures)

    @patch("trevvos_forge.doctor.requests.get")
    def test_timeout_fails_runtime(self, mock_get: MagicMock) -> None:
        import requests as req
        mock_get.side_effect = req.exceptions.Timeout("timed out")
        report = run_ollama_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["runtime_reachable"], "failed")
        self.assertTrue(report.has_failures)

    @patch("trevvos_forge.doctor.requests.get")
    def test_runtime_check_has_duration(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"models": [{"name": "qwen2.5-coder:7b"}]})
        report = run_ollama_doctor(self._settings())
        runtime_check = next(c for c in report.checks if c.name == "runtime_reachable")
        self.assertIsNotNone(runtime_check.duration_seconds)
        self.assertGreaterEqual(runtime_check.duration_seconds, 0)

    @patch("trevvos_forge.doctor.requests.get")
    def test_connection_error_message_mentions_base_url(self, mock_get: MagicMock) -> None:
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("refused")
        report = run_ollama_doctor(self._settings())
        runtime_check = next(c for c in report.checks if c.name == "runtime_reachable")
        self.assertIn("localhost", runtime_check.message)


# ---------------------------------------------------------------------------
# OpenAI-compatible doctor
# ---------------------------------------------------------------------------

class TestOpenAICompatibleDoctor(unittest.TestCase):
    def _settings(
        self,
        model: str = "qwen3-coder",
        base_url: str = "http://localhost:1234/v1",
        api_key: str | None = None,
    ) -> _Settings:
        return _Settings(
            provider="openai-compatible",
            model=model,
            base_url=base_url,
            timeout=30,
            api_key=api_key,
        )

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_models_success_model_found(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"data": [{"id": "qwen3-coder"}]})
        mock_post.return_value = _fake_post_response(200, {
            "choices": [{"message": {"content": "ok"}}]
        })
        report = run_openai_compatible_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["models_endpoint"], "passed")
        self.assertEqual(names["model_present"], "passed")
        self.assertEqual(names["chat_completion"], "passed")
        self.assertFalse(report.has_failures)

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_models_success_model_missing_warns(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"data": [{"id": "other-model"}]})
        mock_post.return_value = _fake_post_response(200, {
            "choices": [{"message": {"content": "ok"}}]
        })
        report = run_openai_compatible_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["model_present"], "warning")
        self.assertFalse(report.has_failures)

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_models_404_warns_and_chat_completion_runs(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        resp_404 = MagicMock()
        resp_404.status_code = 404
        resp_404.raise_for_status.return_value = None
        mock_get.return_value = resp_404

        mock_post.return_value = _fake_post_response(200, {
            "choices": [{"message": {"content": "ok"}}]
        })
        report = run_openai_compatible_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["models_endpoint"], "warning")
        self.assertEqual(names["model_present"], "skipped")
        self.assertEqual(names["chat_completion"], "passed")
        self.assertFalse(report.has_failures)

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_models_401_fails_and_skips_chat(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.raise_for_status.return_value = None
        mock_get.return_value = resp_401

        report = run_openai_compatible_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["models_endpoint"], "failed")
        models_check = next(c for c in report.checks if c.name == "models_endpoint")
        self.assertIn("Authentication", models_check.message)
        self.assertEqual(names["model_present"], "skipped")
        self.assertEqual(names["chat_completion"], "skipped")
        self.assertTrue(report.has_failures)
        mock_post.assert_not_called()

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_models_403_fails(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.raise_for_status.return_value = None
        mock_get.return_value = resp_403

        report = run_openai_compatible_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["models_endpoint"], "failed")
        self.assertTrue(report.has_failures)

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_connection_error_fails_and_skips_chat(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("refused")
        report = run_openai_compatible_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["models_endpoint"], "failed")
        self.assertEqual(names["chat_completion"], "skipped")
        self.assertTrue(report.has_failures)
        mock_post.assert_not_called()

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_timeout_fails_runtime(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        import requests as req
        mock_get.side_effect = req.exceptions.Timeout("timed out")
        report = run_openai_compatible_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["models_endpoint"], "failed")
        self.assertTrue(report.has_failures)

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_chat_completion_invalid_shape_fails(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"data": [{"id": "qwen3-coder"}]})
        mock_post.return_value = _fake_post_response(200, {"no_choices": True})
        report = run_openai_compatible_doctor(self._settings())
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["chat_completion"], "failed")
        self.assertTrue(report.has_failures)

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_api_key_sent_in_authorization_header(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"data": [{"id": "gpt-4"}]})
        mock_post.return_value = _fake_post_response(200, {
            "choices": [{"message": {"content": "ok"}}]
        })
        run_openai_compatible_doctor(self._settings(api_key="sk-test-key", model="gpt-4"))
        _, get_kwargs = mock_get.call_args
        headers = get_kwargs.get("headers", {})
        self.assertIn("Authorization", headers)
        self.assertIn("sk-test-key", headers["Authorization"])

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_no_api_key_no_authorization_header(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"data": []})
        mock_post.return_value = _fake_post_response(200, {
            "choices": [{"message": {"content": "ok"}}]
        })
        run_openai_compatible_doctor(self._settings(api_key=None))
        _, get_kwargs = mock_get.call_args
        headers = get_kwargs.get("headers", {})
        self.assertNotIn("Authorization", headers)

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_api_key_not_leaked_in_check_messages(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.raise_for_status.return_value = None
        mock_get.return_value = resp_401
        report = run_openai_compatible_doctor(self._settings(api_key="sk-super-secret"))
        for check in report.checks:
            self.assertNotIn("sk-super-secret", check.message)
        report_dict = report.to_dict()
        self.assertNotIn("sk-super-secret", json.dumps(report_dict))

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_checks_have_duration_when_available(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"data": [{"id": "qwen3-coder"}]})
        mock_post.return_value = _fake_post_response(200, {
            "choices": [{"message": {"content": "ok"}}]
        })
        report = run_openai_compatible_doctor(self._settings())
        for check in report.checks:
            if check.name in ("models_endpoint", "chat_completion"):
                self.assertIsNotNone(check.duration_seconds, f"{check.name} should have duration")


# ---------------------------------------------------------------------------
# run_doctor dispatch
# ---------------------------------------------------------------------------

class TestRunDoctorDispatch(unittest.TestCase):
    @patch("trevvos_forge.doctor.requests.get")
    def test_dispatches_to_ollama(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"models": []})
        settings = _Settings(provider="ollama")
        report = run_doctor(settings)
        self.assertEqual(report.provider, "ollama")

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_dispatches_to_openai_compatible(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"data": []})
        mock_post.return_value = _fake_post_response(200, {"choices": [{"message": {"content": "ok"}}]})
        settings = _Settings(provider="openai-compatible")
        report = run_doctor(settings)
        self.assertEqual(report.provider, "openai-compatible")

    @patch("trevvos_forge.doctor.requests.post")
    @patch("trevvos_forge.doctor.requests.get")
    def test_dispatches_openai_underscore_alias(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"data": []})
        mock_post.return_value = _fake_post_response(200, {"choices": [{"message": {"content": "ok"}}]})
        settings = _Settings(provider="openai_compatible")
        report = run_doctor(settings)
        self.assertEqual(report.provider, "openai-compatible")

    def test_unknown_provider_returns_failed_report(self) -> None:
        settings = _Settings(provider="unknown-llm")
        report = run_doctor(settings)
        names = {c.name: c.status for c in report.checks}
        self.assertEqual(names["provider_supported"], "failed")
        self.assertTrue(report.has_failures)
        provider_check = next(c for c in report.checks if c.name == "provider_supported")
        self.assertIn("unknown-llm", provider_check.message)
        self.assertIn("ollama", provider_check.message)


# ---------------------------------------------------------------------------
# CLI doctor command
# ---------------------------------------------------------------------------

class TestDoctorCLI(unittest.TestCase):
    @patch("trevvos_forge.doctor.requests.get")
    def test_human_output_contains_provider_and_duration(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {
            "models": [{"name": "qwen2.5-coder:7b"}]
        })
        result = runner.invoke(app, ["doctor"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Provider", result.output)
        self.assertIn("Duration:", result.output)

    @patch("trevvos_forge.doctor.requests.get")
    def test_exit_code_1_on_failure(self, mock_get: MagicMock) -> None:
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("refused")
        result = runner.invoke(app, ["doctor"])
        self.assertEqual(result.exit_code, 1)

    @patch("trevvos_forge.doctor.requests.get")
    def test_json_output_is_valid_json(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {
            "models": [{"name": "qwen2.5-coder:7b"}]
        })
        result = runner.invoke(app, ["doctor", "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output.strip())
        self.assertIn("provider", data)
        self.assertIn("duration_seconds", data)
        self.assertIn("checks", data)

    @patch("trevvos_forge.doctor.requests.get")
    def test_json_output_has_no_plain_duration_line(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"models": []})
        result = runner.invoke(app, ["doctor", "--json"])
        self.assertNotIn("\nDuration:", result.output)

    @patch("trevvos_forge.doctor.requests.get")
    def test_json_does_not_contain_api_key_value(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _fake_get_response(200, {"models": []})
        import os
        with patch.dict(os.environ, {"TREVVOS_FORGE_API_KEY": "sk-leaktest", "TREVVOS_FORGE_PROVIDER": "ollama"}):
            result = runner.invoke(app, ["doctor", "--json"])
        self.assertNotIn("sk-leaktest", result.output)

    @patch("trevvos_forge.doctor.requests.get")
    def test_exit_code_1_on_failed_check_json(self, mock_get: MagicMock) -> None:
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("refused")
        result = runner.invoke(app, ["doctor", "--json"])
        self.assertEqual(result.exit_code, 1)
        data = json.loads(result.output.strip())
        self.assertEqual(data["status"], "failed")


if __name__ == "__main__":
    unittest.main()
