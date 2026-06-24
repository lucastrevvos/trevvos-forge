"""OpenAI-compatible Chat Completions provider."""
from __future__ import annotations

from typing import ClassVar

import requests

from trevvos_forge.exceptions import (
    ProviderConnectionError,
    ProviderHttpError,
    ProviderResponseError,
    ProviderTimeoutError,
)


class OpenAICompatibleProvider:
    """Provider for any endpoint implementing the OpenAI Chat Completions API.

    Works with LM Studio, llama.cpp server, vLLM, LocalAI, Ollama's OpenAI-compat
    mode, OpenRouter, and any other service that exposes /v1/chat/completions.
    """

    name: ClassVar[str] = "openai-compatible"

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        timeout: float | int = 120,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            raise ProviderConnectionError(
                f"Could not connect to OpenAI-compatible provider at {self.base_url}. "
                "Check whether the runtime/server is running."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise ProviderTimeoutError(
                f"OpenAI-compatible provider at {self.base_url} timed out after {self.timeout}s."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderConnectionError(
                f"Unexpected error connecting to OpenAI-compatible provider at {self.base_url}."
            ) from exc

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            raise ProviderHttpError(
                f"OpenAI-compatible provider returned HTTP {response.status_code}."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                "OpenAI-compatible provider returned invalid JSON."
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderResponseError(
                "OpenAI-compatible provider response did not include choices[0].message.content."
            )

        if not isinstance(content, str):
            raise ProviderResponseError(
                "OpenAI-compatible provider response did not include choices[0].message.content."
            )

        return content.strip()
