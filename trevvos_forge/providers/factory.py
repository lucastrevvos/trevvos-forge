"""Factory for building LLM providers from configuration."""
from __future__ import annotations

from trevvos_forge.exceptions import ProviderConfigurationError
from trevvos_forge.providers.ollama import OllamaProvider
from trevvos_forge.settings import ForgeSettings

SUPPORTED_PROVIDERS = ("ollama",)


def build_provider(settings: ForgeSettings) -> OllamaProvider:
    """Return the provider instance for the given settings.

    Defaults to OllamaProvider when settings.provider is "ollama" (the default).
    Raises ProviderConfigurationError for unknown provider names.
    """
    provider_name = getattr(settings, "provider", "ollama")
    if provider_name == "ollama":
        return OllamaProvider(
            model=settings.model,
            base_url=settings.base_url,
            timeout=settings.timeout,
        )
    supported = "\n".join(f"  - {p}" for p in SUPPORTED_PROVIDERS)
    raise ProviderConfigurationError(
        f"Unknown provider: {provider_name}\nSupported providers:\n{supported}"
    )
