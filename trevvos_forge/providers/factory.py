"""Factory for building LLM providers from configuration."""
from __future__ import annotations

from trevvos_forge.exceptions import ProviderConfigurationError
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.providers.openai_compatible import OpenAICompatibleProvider
from trevvos_forge.settings import ForgeSettings

SUPPORTED_PROVIDERS = ("ollama", "openai-compatible")


def build_provider(settings: ForgeSettings) -> OllamaProvider | OpenAICompatibleProvider:
    """Return the provider instance for the given settings.

    Dispatches by settings.provider; raises ProviderConfigurationError for
    unknown provider names.
    """
    provider_name = getattr(settings, "provider", "ollama")

    if provider_name == "ollama":
        return OllamaProvider(
            model=settings.model,
            base_url=settings.base_url,
            timeout=settings.timeout,
        )

    if provider_name in ("openai-compatible", "openai_compatible"):
        return OpenAICompatibleProvider(
            model=settings.model,
            base_url=settings.base_url,
            api_key=getattr(settings, "api_key", None),
            timeout=settings.timeout,
        )

    supported = "\n".join(f"  - {p}" for p in SUPPORTED_PROVIDERS)
    raise ProviderConfigurationError(
        f"Unknown provider: {provider_name}\nSupported providers:\n{supported}"
    )
