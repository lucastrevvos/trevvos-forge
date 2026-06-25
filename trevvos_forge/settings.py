import os
from dataclasses import dataclass

from trevvos_forge.exceptions import ConfigurationError

@dataclass(frozen=True)
class ForgeSettings:
    model: str
    base_url: str
    timeout: int
    provider: str = "ollama"
    api_key: str | None = None
    runtime: str | None = None

    @classmethod
    def from_env(cls) -> "ForgeSettings":
        model = os.getenv("TREVVOS_FORGE_MODEL","qwen2.5-coder:7b")
        base_url = os.getenv("TREVVOS_FORGE_BASE_URL","http://localhost:11434")
        timeout_raw = os.getenv("TREVVOS_FORGE_TIMEOUT", "320")
        provider = os.getenv("TREVVOS_FORGE_PROVIDER", "ollama")
        api_key = os.getenv("TREVVOS_FORGE_API_KEY") or None
        runtime = os.getenv("TREVVOS_FORGE_RUNTIME") or None

        try:
            timeout = int(timeout_raw)
        except ValueError as exc:
            raise ConfigurationError(
                f"TREVVOS_FORGE_TIMEOUT must be an integer.Current value: {timeout_raw!r}."
            ) from exc

        if timeout <= 0:
            raise ConfigurationError(
                f"TREVVOS_FORGE_TIMEOUT must be greater than zero. Current value: {timeout}"
            )

        return cls(
            model=model,
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            provider=provider,
            api_key=api_key,
            runtime=runtime,
        )
