"""Runtime abstraction — shared types and Protocol."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class RuntimeStatus:
    runtime: str
    is_supported: bool
    is_running: bool | None
    base_url: str | None
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "runtime": self.runtime,
            "is_supported": self.is_supported,
            "message": self.message,
        }
        if self.is_running is not None:
            d["is_running"] = self.is_running
        if self.base_url is not None:
            d["base_url"] = self.base_url
        if self.details is not None:
            d["details"] = self.details
        return d


@dataclass
class RuntimeActionResult:
    runtime: str
    action: str
    status: str  # succeeded, failed, skipped, unsupported
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "runtime": self.runtime,
            "action": self.action,
            "status": self.status,
            "message": self.message,
        }
        if self.details is not None:
            d["details"] = self.details
        return d


@runtime_checkable
class RuntimeManager(Protocol):
    name: str

    def status(self) -> RuntimeStatus: ...
    def start(self) -> RuntimeActionResult: ...
    def stop(self) -> RuntimeActionResult: ...
