"""Tests for the provider abstraction layer (Marco 72)."""
import unittest
from unittest.mock import patch

from trevvos_forge.exceptions import ProviderConfigurationError
from trevvos_forge.providers.base import LlmProvider, LLMProvider
from trevvos_forge.providers.factory import build_provider, SUPPORTED_PROVIDERS
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.settings import ForgeSettings


# ---------------------------------------------------------------------------
# Minimal FakeProvider that satisfies the LlmProvider protocol
# ---------------------------------------------------------------------------

class _FakeProvider:
    name = "fake"
    model: str | None = "fake-model"

    def generate(self, prompt: str) -> str:
        return f"fake response to: {prompt}"


# ---------------------------------------------------------------------------
# Protocol compatibility
# ---------------------------------------------------------------------------

class TestLlmProviderProtocol(unittest.TestCase):
    def test_fake_provider_has_required_attributes(self) -> None:
        p = _FakeProvider()
        self.assertEqual(p.name, "fake")
        self.assertEqual(p.model, "fake-model")
        self.assertIsInstance(p.generate("hi"), str)

    def test_llmprovider_alias_is_same_as_llmprovider(self) -> None:
        self.assertIs(LlmProvider, LLMProvider)

    def test_ollama_provider_satisfies_protocol(self) -> None:
        p = OllamaProvider(model="qwen2.5-coder:7b")
        self.assertEqual(p.name, "ollama")
        self.assertEqual(p.model, "qwen2.5-coder:7b")
        self.assertTrue(callable(p.generate))

    def test_ollama_name_is_class_var(self) -> None:
        self.assertEqual(OllamaProvider.name, "ollama")


# ---------------------------------------------------------------------------
# Factory: default provider
# ---------------------------------------------------------------------------

class TestBuildProviderFactory(unittest.TestCase):
    def _settings(self, **kwargs) -> ForgeSettings:
        base = dict(model="qwen2.5-coder:7b", base_url="http://localhost:11434", timeout=120)
        base.update(kwargs)
        return ForgeSettings(**base)

    def test_default_provider_is_ollama(self) -> None:
        settings = self._settings()
        provider = build_provider(settings)
        self.assertIsInstance(provider, OllamaProvider)

    def test_explicit_ollama_returns_ollama_provider(self) -> None:
        settings = self._settings(provider="ollama")
        provider = build_provider(settings)
        self.assertIsInstance(provider, OllamaProvider)

    def test_ollama_provider_gets_settings_values(self) -> None:
        settings = self._settings(model="llama3:8b", base_url="http://custom:11434", timeout=60)
        provider = build_provider(settings)
        self.assertIsInstance(provider, OllamaProvider)
        self.assertEqual(provider.model, "llama3:8b")
        self.assertEqual(provider.base_url, "http://custom:11434")
        self.assertEqual(provider.timeout, 60)

    def test_unknown_provider_raises_configuration_error(self) -> None:
        settings = self._settings(provider="unknown")
        with self.assertRaises(ProviderConfigurationError) as ctx:
            build_provider(settings)
        self.assertIn("Unknown provider: unknown", str(ctx.exception))

    def test_unknown_provider_error_lists_supported(self) -> None:
        settings = self._settings(provider="openai")
        with self.assertRaises(ProviderConfigurationError) as ctx:
            build_provider(settings)
        error_msg = str(ctx.exception)
        for p in SUPPORTED_PROVIDERS:
            self.assertIn(p, error_msg)

    def test_supported_providers_includes_ollama(self) -> None:
        self.assertIn("ollama", SUPPORTED_PROVIDERS)


# ---------------------------------------------------------------------------
# Settings: provider field
# ---------------------------------------------------------------------------

class TestForgeSettingsProvider(unittest.TestCase):
    def test_default_provider_is_ollama(self) -> None:
        settings = ForgeSettings(model="x", base_url="y", timeout=30)
        self.assertEqual(settings.provider, "ollama")

    def test_explicit_provider_field(self) -> None:
        settings = ForgeSettings(model="x", base_url="y", timeout=30, provider="ollama")
        self.assertEqual(settings.provider, "ollama")

    def test_from_env_defaults_to_ollama(self) -> None:
        import os
        env = {k: v for k, v in os.environ.items()}
        env.pop("TREVVOS_FORGE_PROVIDER", None)
        with patch.dict(os.environ, env, clear=True):
            settings = ForgeSettings.from_env()
        self.assertEqual(settings.provider, "ollama")

    def test_from_env_reads_provider_env_var(self) -> None:
        import os
        with patch.dict(os.environ, {"TREVVOS_FORGE_PROVIDER": "custom"}):
            settings = ForgeSettings.from_env()
        self.assertEqual(settings.provider, "custom")


# ---------------------------------------------------------------------------
# CLI patch point preserved
# ---------------------------------------------------------------------------

class TestCliPatchPoint(unittest.TestCase):
    def test_cli_build_provider_is_patchable(self) -> None:
        fake = _FakeProvider()
        with patch("trevvos_forge.cli.build_provider", return_value=fake) as mock_bp:
            import trevvos_forge.cli as cli_module
            result = cli_module.build_provider(
                ForgeSettings(model="x", base_url="y", timeout=10)
            )
        mock_bp.assert_called_once()
        self.assertIs(result, fake)

    def test_cli_build_provider_delegates_to_factory(self) -> None:
        settings = ForgeSettings(model="qwen2.5-coder:7b", base_url="http://localhost:11434", timeout=120)
        import trevvos_forge.cli as cli_module
        with patch("trevvos_forge.cli._build_provider_factory") as mock_factory:
            mock_factory.return_value = _FakeProvider()
            cli_module.build_provider(settings)
        mock_factory.assert_called_once_with(settings)
