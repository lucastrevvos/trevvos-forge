"""Centralized secret masking for Trevvos Forge exports and APIs."""
from __future__ import annotations

from typing import Any

_SENSITIVE_KEYS = frozenset({"api_key", "token", "secret", "password", "authorization", "auth"})


def mask_secrets(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: "present" if k.lower() in _SENSITIVE_KEYS else mask_secrets(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [mask_secrets(item) for item in data]
    return data
