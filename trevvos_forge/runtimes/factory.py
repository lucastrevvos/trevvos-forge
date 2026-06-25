"""Factory for RuntimeManager instances."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from trevvos_forge.exceptions import RuntimeConfigurationError
from trevvos_forge.runtimes.base import RuntimeManager
from trevvos_forge.runtimes.external import ExternalRuntime
from trevvos_forge.runtimes.ollama import OllamaRuntime

SUPPORTED_RUNTIMES = ("external", "ollama")


def _resolve_runtime_name(settings: Any) -> str:
    runtime = getattr(settings, "runtime", None)
    if runtime:
        return runtime
    provider = getattr(settings, "provider", "ollama")
    if provider == "ollama":
        return "ollama"
    return "external"


def build_runtime_manager(
    settings: Any,
    workspace_root: Path | None = None,
) -> RuntimeManager:
    runtime_name = _resolve_runtime_name(settings)

    if runtime_name == "external":
        return ExternalRuntime(base_url=getattr(settings, "base_url", None))

    if runtime_name == "ollama":
        return OllamaRuntime(
            base_url=getattr(settings, "base_url", "http://localhost:11434"),
            timeout=getattr(settings, "timeout", 120),
            workspace_root=workspace_root,
        )

    supported = ", ".join(SUPPORTED_RUNTIMES)
    raise RuntimeConfigurationError(
        f"Unknown runtime: {runtime_name!r}. Supported runtimes: {supported}."
    )
