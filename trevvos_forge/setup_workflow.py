"""Guided setup workflow for Trevvos Forge — creates/updates .trevvos/config.json."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trevvos_forge.config_store import load_config, normalize_language, save_config
from trevvos_forge.doctor import run_doctor as _run_doctor
from trevvos_forge.exceptions import ConfigurationError
from trevvos_forge.project_scanner import save_project_profile, scan_project
from trevvos_forge.providers.factory import SUPPORTED_PROVIDERS
from trevvos_forge.runtimes.factory import SUPPORTED_RUNTIMES
from trevvos_forge.settings import ForgeSettings

_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "qwen2.5-coder:7b",
        "runtime": "ollama",
    },
    "openai-compatible": {
        "base_url": "http://localhost:1234/v1",
        "model": "qwen3-coder",
        "runtime": "external",
    },
}


@dataclass
class SetupRequest:
    workspace_root: Path
    provider: str | None = None
    runtime: str | None = None
    base_url: str | None = None
    model: str | None = None
    language: str | None = None
    test_commands: list[str] | None = None
    yes: bool = False
    run_doctor: bool = True
    run_inspect: bool = True
    dry_run: bool = False


@dataclass
class SetupResult:
    status: str
    workspace_root: Path
    config_path: Path | None
    provider: str
    runtime: str
    base_url: str
    model: str
    language: str
    test_commands: list[str]
    doctor: dict[str, Any] | None
    project_profile_written: bool
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "workspace": str(self.workspace_root),
            "config_path": str(self.config_path) if self.config_path else None,
            "provider": self.provider,
            "runtime": self.runtime,
            "base_url": self.base_url,
            "model": self.model,
            "language": self.language,
            "test_commands": self.test_commands,
            "doctor": self.doctor,
            "project_profile_written": self.project_profile_written,
            "duration_seconds": self.duration_seconds,
        }


def run_setup(request: SetupRequest) -> SetupResult:
    t0 = time.perf_counter()
    workspace_root = request.workspace_root.resolve()

    # Validate provider
    provider = (request.provider or "ollama").lower().strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigurationError(
            f"Unknown provider: {provider!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    # Resolve per-provider defaults
    defaults = _PROVIDER_DEFAULTS[provider]
    base_url = ((request.base_url or defaults["base_url"]) or "").rstrip("/")
    model = request.model or defaults["model"]
    runtime = request.runtime or defaults["runtime"]

    if runtime not in SUPPORTED_RUNTIMES:
        raise ConfigurationError(
            f"Unknown runtime: {runtime!r}. Supported: {', '.join(SUPPORTED_RUNTIMES)}"
        )

    # Load existing config (to preserve unrelated keys and get language default)
    try:
        existing_config: dict[str, Any] = load_config(workspace_root)
    except ConfigurationError:
        existing_config = {}

    # Language: explicit request → existing config → default "en"
    raw_language = request.language or existing_config.get("language") or "en"
    try:
        language = normalize_language(str(raw_language))
    except ConfigurationError:
        language = "en"

    # Project scanning — only when run_inspect=True
    profile: dict[str, Any] | None = None
    detected_test_commands: list[str] = []
    project_profile_written = False

    if request.run_inspect:
        try:
            profile = scan_project(workspace_root)
            detected_test_commands = list(profile.get("suggested_test_commands") or [])
        except Exception:
            profile = None

    # Determine final test commands
    if request.test_commands is not None:
        final_test_commands = list(request.test_commands)
    elif detected_test_commands:
        final_test_commands = detected_test_commands
    else:
        existing_cmds = existing_config.get("test_commands")
        final_test_commands = list(existing_cmds) if isinstance(existing_cmds, list) else []

    # Build config delta (never include api_key)
    config_delta: dict[str, Any] = {
        "provider": provider,
        "runtime": runtime,
        "base_url": base_url,
        "model": model,
        "language": language,
    }
    if final_test_commands:
        config_delta["test_commands"] = final_test_commands

    # Write config (unless dry_run)
    config_path: Path | None = None
    if not request.dry_run:
        merged = {**existing_config, **config_delta}
        config_path = save_config(workspace_root, merged)

        if profile is not None:
            save_project_profile(workspace_root, profile)
            project_profile_written = True

    # Run doctor (unless skipped)
    doctor_result: dict[str, Any] | None = None
    if request.run_doctor:
        try:
            doctor_settings = ForgeSettings(
                model=model,
                base_url=base_url,
                provider=provider,
                timeout=320,
                api_key=os.getenv("TREVVOS_FORGE_API_KEY") or None,
                runtime=runtime,
            )
            report = _run_doctor(doctor_settings)
            doctor_result = {
                "status": report.status,
                "checks": len(report.checks),
                "has_failures": report.has_failures,
            }
        except Exception as exc:
            doctor_result = {"status": "error", "error": str(exc)}

    return SetupResult(
        status="succeeded",
        workspace_root=workspace_root,
        config_path=config_path,
        provider=provider,
        runtime=runtime,
        base_url=base_url,
        model=model,
        language=language,
        test_commands=final_test_commands,
        doctor=doctor_result,
        project_profile_written=project_profile_written,
        duration_seconds=round(time.perf_counter() - t0, 2),
    )
