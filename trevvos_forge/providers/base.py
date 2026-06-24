from __future__ import annotations

from typing import Protocol


class LlmProvider(Protocol):
    name: str
    model: str | None

    def generate(self, prompt: str) -> str: ...


# Backward-compatible alias (engine.py imports LLMProvider)
LLMProvider = LlmProvider
