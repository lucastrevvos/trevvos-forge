"""ExternalRuntime — represents runtimes managed outside Trevvos Forge."""
from __future__ import annotations

from typing import ClassVar

from trevvos_forge.runtimes.base import RuntimeActionResult, RuntimeStatus


class ExternalRuntime:
    """Represents a runtime (API, server, cloud) managed entirely by the user.

    Examples: OpenAI API, OpenRouter, manually-started LM Studio, llama.cpp,
    vLLM, LocalAI, or any other endpoint the user operates independently.
    """

    name: ClassVar[str] = "external"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            runtime=self.name,
            is_supported=True,
            is_running=None,
            base_url=self.base_url,
            message="External runtime; managed outside Trevvos Forge.",
        )

    def start(self) -> RuntimeActionResult:
        return RuntimeActionResult(
            runtime=self.name,
            action="start",
            status="unsupported",
            message="External runtime cannot be started by Trevvos Forge. Start it manually.",
        )

    def stop(self) -> RuntimeActionResult:
        return RuntimeActionResult(
            runtime=self.name,
            action="stop",
            status="unsupported",
            message="External runtime cannot be stopped by Trevvos Forge. Stop it manually.",
        )
