"""Tests for OpenAICompatibleProvider (Marco 73)."""
import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from trevvos_forge.exceptions import (
    ProviderConnectionError,
    ProviderHttpError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from trevvos_forge.providers.factory import build_provider, SUPPORTED_PROVIDERS
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.providers.openai_compatible import OpenAICompatibleProvider
from trevvos_forge.settings import ForgeSettings


def _make_response(body: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _ok_response(content: str = "ok") -> MagicMock:
    return _make_response({"choices": [{"message": {"content": content}}]})


class TestOpenAICompatibleProviderInit(unittest.TestCase):
    def test_name_class_var(self) -> None:
        self.assertEqual(OpenAICompatibleProvider.name, "openai-compatible")

    def test_instance_name(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://localhost:1234/v1")
        self.assertEqual(p.name, "openai-compatible")

    def test_model_stored(self) -> None:
        p = OpenAICompatibleProvider(model="my-model", base_url="http://h/v1")
        self.assertEqual(p.model, "my-model")

    def test_base_url_strips_trailing_slash(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://localhost:1234/v1/")
        self.assertEqual(p.base_url, "http://localhost:1234/v1")

    def test_api_key_defaults_none(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        self.assertIsNone(p.api_key)

    def test_timeout_default(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        self.assertEqual(p.timeout, 120)

    def test_satisfies_llm_provider_protocol(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        self.assertTrue(callable(p.generate))
        self.assertIsInstance(p.name, str)
        self.assertIsInstance(p.model, str)


class TestOpenAICompatibleProviderEndpoint(unittest.TestCase):
    def test_endpoint_built_without_trailing_slash(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://localhost:1234/v1")
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            p.generate("hi")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        self.assertEqual(url, "http://localhost:1234/v1/chat/completions")

    def test_endpoint_built_with_trailing_slash(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://localhost:1234/v1/")
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            p.generate("hi")
        url = mock_post.call_args[0][0]
        self.assertEqual(url, "http://localhost:1234/v1/chat/completions")

    def test_endpoint_llama_cpp_style(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://localhost:8080/v1")
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            p.generate("hello")
        url = mock_post.call_args[0][0]
        self.assertEqual(url, "http://localhost:8080/v1/chat/completions")


class TestOpenAICompatibleProviderPayload(unittest.TestCase):
    def test_payload_structure(self) -> None:
        p = OpenAICompatibleProvider(model="test-model", base_url="http://h/v1")
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            p.generate("hello")
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(payload["temperature"], 0)

    def test_content_type_header(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            p.generate("hello")
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_timeout_passed_to_request(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1", timeout=30)
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            p.generate("hello")
        timeout = mock_post.call_args[1]["timeout"]
        self.assertEqual(timeout, 30)


class TestOpenAICompatibleProviderApiKey(unittest.TestCase):
    def test_no_api_key_omits_authorization(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1", api_key=None)
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            p.generate("hello")
        headers = mock_post.call_args[1]["headers"]
        self.assertNotIn("Authorization", headers)

    def test_api_key_sets_bearer_header(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1", api_key="test-key")
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            p.generate("hello")
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer test-key")

    def test_empty_string_api_key_omits_authorization(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1", api_key="")
        with patch("requests.post", return_value=_ok_response()) as mock_post:
            p.generate("hello")
        headers = mock_post.call_args[1]["headers"]
        self.assertNotIn("Authorization", headers)


class TestOpenAICompatibleProviderResponseParsing(unittest.TestCase):
    def test_success_returns_content(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=_ok_response("hello world")):
            result = p.generate("test")
        self.assertEqual(result, "hello world")

    def test_content_is_stripped(self) -> None:
        resp = _make_response({"choices": [{"message": {"content": "  trimmed  "}}]})
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=resp):
            result = p.generate("test")
        self.assertEqual(result, "trimmed")

    def test_missing_choices_raises_response_error(self) -> None:
        resp = _make_response({"result": "something else"})
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=resp):
            with self.assertRaises(ProviderResponseError) as ctx:
                p.generate("test")
        self.assertIn("choices[0].message.content", str(ctx.exception))

    def test_empty_choices_raises_response_error(self) -> None:
        resp = _make_response({"choices": []})
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=resp):
            with self.assertRaises(ProviderResponseError):
                p.generate("test")

    def test_missing_message_raises_response_error(self) -> None:
        resp = _make_response({"choices": [{"index": 0}]})
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=resp):
            with self.assertRaises(ProviderResponseError):
                p.generate("test")

    def test_missing_content_raises_response_error(self) -> None:
        resp = _make_response({"choices": [{"message": {"role": "assistant"}}]})
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=resp):
            with self.assertRaises(ProviderResponseError):
                p.generate("test")

    def test_non_string_content_raises_response_error(self) -> None:
        resp = _make_response({"choices": [{"message": {"content": 42}}]})
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=resp):
            with self.assertRaises(ProviderResponseError):
                p.generate("test")

    def test_invalid_json_raises_response_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("bad json")
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=mock_resp):
            with self.assertRaises(ProviderResponseError) as ctx:
                p.generate("test")
        self.assertIn("invalid JSON", str(ctx.exception))


class TestOpenAICompatibleProviderErrors(unittest.TestCase):
    def test_connection_error_raises_provider_connection_error(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(ProviderConnectionError) as ctx:
                p.generate("test")
        self.assertIn("http://h/v1", str(ctx.exception))
        self.assertIn("runtime/server is running", str(ctx.exception))

    def test_timeout_raises_provider_timeout_error(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1", timeout=5)
        with patch("requests.post", side_effect=requests.exceptions.Timeout()):
            with self.assertRaises(ProviderTimeoutError) as ctx:
                p.generate("test")
        self.assertIn("5", str(ctx.exception))

    def test_request_exception_raises_connection_error(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", side_effect=requests.exceptions.RequestException()):
            with self.assertRaises(ProviderConnectionError):
                p.generate("test")

    def test_http_401_raises_provider_http_error(self) -> None:
        resp = _make_response({}, status_code=401)
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=resp):
            with self.assertRaises(ProviderHttpError) as ctx:
                p.generate("test")
        self.assertIn("401", str(ctx.exception))

    def test_http_500_raises_provider_http_error(self) -> None:
        resp = _make_response({}, status_code=500)
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1")
        with patch("requests.post", return_value=resp):
            with self.assertRaises(ProviderHttpError) as ctx:
                p.generate("test")
        self.assertIn("500", str(ctx.exception))

    def test_error_message_does_not_contain_api_key(self) -> None:
        p = OpenAICompatibleProvider(model="m", base_url="http://h/v1", api_key="secret-key")
        resp = _make_response({}, status_code=401)
        with patch("requests.post", return_value=resp):
            with self.assertRaises(ProviderHttpError) as ctx:
                p.generate("test")
        self.assertNotIn("secret-key", str(ctx.exception))


class TestFactoryOpenAICompatible(unittest.TestCase):
    def _settings(self, **kwargs) -> ForgeSettings:
        base = dict(model="qwen3-coder", base_url="http://localhost:1234/v1", timeout=120)
        base.update(kwargs)
        return ForgeSettings(**base)

    def test_openai_compatible_provider_selected(self) -> None:
        settings = self._settings(provider="openai-compatible")
        provider = build_provider(settings)
        self.assertIsInstance(provider, OpenAICompatibleProvider)

    def test_openai_compatible_underscore_alias(self) -> None:
        settings = self._settings(provider="openai_compatible")
        provider = build_provider(settings)
        self.assertIsInstance(provider, OpenAICompatibleProvider)

    def test_openai_compatible_gets_settings_values(self) -> None:
        settings = self._settings(
            provider="openai-compatible",
            model="llama3",
            base_url="http://localhost:8080/v1",
            timeout=60,
            api_key="mykey",
        )
        provider = build_provider(settings)
        self.assertIsInstance(provider, OpenAICompatibleProvider)
        self.assertEqual(provider.model, "llama3")
        self.assertEqual(provider.base_url, "http://localhost:8080/v1")
        self.assertEqual(provider.timeout, 60)
        self.assertEqual(provider.api_key, "mykey")

    def test_default_provider_still_ollama(self) -> None:
        settings = self._settings(provider="ollama")
        provider = build_provider(settings)
        self.assertIsInstance(provider, OllamaProvider)

    def test_supported_providers_includes_openai_compatible(self) -> None:
        self.assertIn("openai-compatible", SUPPORTED_PROVIDERS)
        self.assertIn("ollama", SUPPORTED_PROVIDERS)

    def test_unknown_provider_error_mentions_openai_compatible(self) -> None:
        from trevvos_forge.exceptions import ProviderConfigurationError
        settings = self._settings(provider="anthropic")
        with self.assertRaises(ProviderConfigurationError) as ctx:
            build_provider(settings)
        msg = str(ctx.exception)
        self.assertIn("openai-compatible", msg)
        self.assertIn("ollama", msg)


class TestSettingsApiKey(unittest.TestCase):
    def test_api_key_default_is_none(self) -> None:
        settings = ForgeSettings(model="m", base_url="http://h", timeout=30)
        self.assertIsNone(settings.api_key)

    def test_api_key_explicit(self) -> None:
        settings = ForgeSettings(model="m", base_url="http://h", timeout=30, api_key="abc")
        self.assertEqual(settings.api_key, "abc")

    def test_from_env_reads_api_key(self) -> None:
        import os
        with patch.dict(os.environ, {"TREVVOS_FORGE_API_KEY": "env-key"}):
            settings = ForgeSettings.from_env()
        self.assertEqual(settings.api_key, "env-key")

    def test_from_env_api_key_defaults_none(self) -> None:
        import os
        env = {k: v for k, v in os.environ.items()}
        env.pop("TREVVOS_FORGE_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            settings = ForgeSettings.from_env()
        self.assertIsNone(settings.api_key)
