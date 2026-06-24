"""Doctor module — runtime detection and provider health checks."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

from trevvos_forge.providers.factory import SUPPORTED_PROVIDERS


@dataclass
class DoctorCheck:
    name: str
    status: str  # passed, failed, skipped, warning
    message: str
    duration_seconds: float | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "message": self.message,
        }
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        if self.details is not None:
            d["details"] = self.details
        return d


@dataclass
class DoctorReport:
    provider: str
    model: str | None
    base_url: str | None
    checks: list[DoctorCheck]
    duration_seconds: float
    api_key_present: bool = False

    @property
    def status(self) -> str:
        if any(c.status == "failed" for c in self.checks):
            return "failed"
        if any(c.status == "warning" for c in self.checks):
            return "warning"
        return "passed"

    @property
    def has_failures(self) -> bool:
        return any(c.status == "failed" for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key": "present" if self.api_key_present else "not set",
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "checks": [c.to_dict() for c in self.checks],
        }


def run_doctor(settings: Any) -> DoctorReport:
    """Dispatch to the appropriate provider doctor based on settings.provider."""
    provider_name = getattr(settings, "provider", "ollama")

    if provider_name == "ollama":
        return run_ollama_doctor(settings)

    if provider_name in ("openai-compatible", "openai_compatible"):
        return run_openai_compatible_doctor(settings)

    # Unknown provider
    t0 = time.perf_counter()
    supported = ", ".join(SUPPORTED_PROVIDERS)
    checks: list[DoctorCheck] = [
        DoctorCheck(name="config_loaded", status="passed", message="Configuration loaded"),
        DoctorCheck(
            name="provider_supported",
            status="failed",
            message=f"Unknown provider: {provider_name!r}. Supported providers: {supported}.",
        ),
    ]
    return DoctorReport(
        provider=provider_name,
        model=getattr(settings, "model", None),
        base_url=getattr(settings, "base_url", None),
        checks=checks,
        duration_seconds=round(time.perf_counter() - t0, 2),
        api_key_present=bool(getattr(settings, "api_key", None)),
    )


def run_ollama_doctor(settings: Any) -> DoctorReport:
    """Run doctor checks for the Ollama provider."""
    t0 = time.perf_counter()
    checks: list[DoctorCheck] = []
    base_url: str = getattr(settings, "base_url", "http://localhost:11434")
    model: str = getattr(settings, "model", "")
    timeout: int = getattr(settings, "timeout", 120)

    checks.append(DoctorCheck(name="config_loaded", status="passed", message="Configuration loaded"))
    checks.append(DoctorCheck(name="provider_supported", status="passed", message="Provider 'ollama' is supported"))

    # Runtime reachable + model list
    t = time.perf_counter()
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        duration = round(time.perf_counter() - t, 2)

        raw_models = data.get("models", [])
        model_names: list[str] = []
        for item in raw_models:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if isinstance(name, str):
                    model_names.append(name)

        checks.append(DoctorCheck(
            name="runtime_reachable",
            status="passed",
            message="Ollama runtime reachable (/api/tags)",
            duration_seconds=duration,
        ))

        if model in model_names:
            checks.append(DoctorCheck(
                name="model_present",
                status="passed",
                message=f"Model {model} found",
            ))
        else:
            checks.append(DoctorCheck(
                name="model_present",
                status="warning",
                message=f"Model {model} not found in Ollama. Run: ollama pull {model}",
            ))

    except requests.exceptions.ConnectionError:
        duration = round(time.perf_counter() - t, 2)
        checks.append(DoctorCheck(
            name="runtime_reachable",
            status="failed",
            message=f"Could not connect to Ollama at {base_url}. Is Ollama running?",
            duration_seconds=duration,
        ))
        checks.append(DoctorCheck(name="model_present", status="skipped", message="Skipped: runtime not reachable"))

    except requests.exceptions.Timeout:
        duration = round(time.perf_counter() - t, 2)
        checks.append(DoctorCheck(
            name="runtime_reachable",
            status="failed",
            message=f"Ollama at {base_url} timed out.",
            duration_seconds=duration,
        ))
        checks.append(DoctorCheck(name="model_present", status="skipped", message="Skipped: runtime not reachable"))

    except (requests.exceptions.HTTPError, requests.exceptions.RequestException, ValueError):
        duration = round(time.perf_counter() - t, 2)
        checks.append(DoctorCheck(
            name="runtime_reachable",
            status="failed",
            message=f"Ollama at {base_url} returned an unexpected error.",
            duration_seconds=duration,
        ))
        checks.append(DoctorCheck(name="model_present", status="skipped", message="Skipped: runtime not reachable"))

    return DoctorReport(
        provider="ollama",
        model=model,
        base_url=base_url,
        checks=checks,
        duration_seconds=round(time.perf_counter() - t0, 2),
        api_key_present=bool(getattr(settings, "api_key", None)),
    )


def run_openai_compatible_doctor(settings: Any) -> DoctorReport:
    """Run doctor checks for the OpenAI-compatible provider."""
    t0 = time.perf_counter()
    checks: list[DoctorCheck] = []
    base_url: str = getattr(settings, "base_url", "").rstrip("/")
    model: str = getattr(settings, "model", "")
    api_key: str | None = getattr(settings, "api_key", None)
    timeout: int = getattr(settings, "timeout", 120)

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    checks.append(DoctorCheck(name="config_loaded", status="passed", message="Configuration loaded"))
    checks.append(DoctorCheck(name="provider_supported", status="passed", message="Provider 'openai-compatible' is supported"))

    # Models endpoint check
    t = time.perf_counter()
    runtime_is_up = False
    models_available = False
    model_names: list[str] = []

    try:
        resp = requests.get(f"{base_url}/models", headers=headers, timeout=timeout)
        duration = round(time.perf_counter() - t, 2)

        if resp.status_code == 404:
            checks.append(DoctorCheck(
                name="models_endpoint",
                status="warning",
                message="Models endpoint not available (/models returned 404). Some runtimes don't implement it.",
                duration_seconds=duration,
            ))
            runtime_is_up = True
            models_available = False

        elif resp.status_code in (401, 403):
            checks.append(DoctorCheck(
                name="models_endpoint",
                status="failed",
                message=f"Authentication failed (HTTP {resp.status_code}). Check TREVVOS_FORGE_API_KEY.",
                duration_seconds=duration,
            ))
            runtime_is_up = False
            models_available = False

        else:
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("data", []):
                if isinstance(item, dict):
                    model_id = item.get("id")
                    if isinstance(model_id, str):
                        model_names.append(model_id)
            checks.append(DoctorCheck(
                name="models_endpoint",
                status="passed",
                message="Runtime reachable (/models)",
                duration_seconds=duration,
            ))
            runtime_is_up = True
            models_available = True

    except requests.exceptions.ConnectionError:
        duration = round(time.perf_counter() - t, 2)
        checks.append(DoctorCheck(
            name="models_endpoint",
            status="failed",
            message=(
                f"Could not connect to openai-compatible runtime at {base_url}. "
                "Check whether LM Studio/llama.cpp/vLLM/LocalAI is running."
            ),
            duration_seconds=duration,
        ))

    except requests.exceptions.Timeout:
        duration = round(time.perf_counter() - t, 2)
        checks.append(DoctorCheck(
            name="models_endpoint",
            status="failed",
            message="Provider timed out.",
            duration_seconds=duration,
        ))

    except (requests.exceptions.RequestException, ValueError):
        duration = round(time.perf_counter() - t, 2)
        checks.append(DoctorCheck(
            name="models_endpoint",
            status="failed",
            message=f"Unexpected error contacting {base_url}/models.",
            duration_seconds=duration,
        ))

    # Model present check
    if models_available:
        if model in model_names:
            checks.append(DoctorCheck(name="model_present", status="passed", message=f"Model {model} found"))
        else:
            checks.append(DoctorCheck(
                name="model_present",
                status="warning",
                message=f"Model {model} not found in /models response.",
            ))
    else:
        checks.append(DoctorCheck(name="model_present", status="skipped", message="Skipped: could not list models"))

    # Chat completion check (only when runtime is reachable)
    if runtime_is_up:
        t = time.perf_counter()
        try:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with only: ok"}],
                "temperature": 0,
            }
            resp = requests.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            duration = round(time.perf_counter() - t, 2)

            if resp.status_code in (401, 403):
                checks.append(DoctorCheck(
                    name="chat_completion",
                    status="failed",
                    message=f"Authentication failed (HTTP {resp.status_code}). Check TREVVOS_FORGE_API_KEY.",
                    duration_seconds=duration,
                ))
            else:
                resp.raise_for_status()
                data = resp.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                    if not isinstance(content, str):
                        raise TypeError
                    checks.append(DoctorCheck(
                        name="chat_completion",
                        status="passed",
                        message="Chat completions check passed",
                        duration_seconds=duration,
                    ))
                except (KeyError, IndexError, TypeError):
                    checks.append(DoctorCheck(
                        name="chat_completion",
                        status="failed",
                        message="Response did not include choices[0].message.content.",
                        duration_seconds=duration,
                    ))

        except requests.exceptions.ConnectionError:
            duration = round(time.perf_counter() - t, 2)
            checks.append(DoctorCheck(
                name="chat_completion",
                status="failed",
                message=f"Could not connect to openai-compatible runtime at {base_url}.",
                duration_seconds=duration,
            ))

        except requests.exceptions.Timeout:
            duration = round(time.perf_counter() - t, 2)
            checks.append(DoctorCheck(
                name="chat_completion",
                status="failed",
                message=f"Provider timed out after {timeout}s.",
                duration_seconds=duration,
            ))

        except (requests.exceptions.RequestException, ValueError):
            duration = round(time.perf_counter() - t, 2)
            checks.append(DoctorCheck(
                name="chat_completion",
                status="failed",
                message="Unexpected error during chat completion check.",
                duration_seconds=duration,
            ))
    else:
        checks.append(DoctorCheck(
            name="chat_completion",
            status="skipped",
            message="Skipped: runtime not reachable",
        ))

    return DoctorReport(
        provider="openai-compatible",
        model=model,
        base_url=base_url,
        checks=checks,
        duration_seconds=round(time.perf_counter() - t0, 2),
        api_key_present=bool(api_key),
    )
