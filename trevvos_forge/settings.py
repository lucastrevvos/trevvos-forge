import os
from dataclasses import dataclass

@dataclass(frozen=True)
class ForgeSettings:
    model: str
    base_url: str
    timeout: int

    @classmethod
    def from_env(cls) -> "ForgeSettings":
        model = os.getenv("TREVVOS_FORGE_MODEL","qwen2.5-coder:7b")
        base_url = os.getenv("TREVVOS_FORGE_BASE_URL","http://localhost:11434")
        timeout = int(os.getenv("TREVVOS_FORGE_TIMEOUT", "120"))

        return cls(
            model=model,
            base_url=base_url,
            timeout=timeout
        )
