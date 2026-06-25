"""OllamaRuntime — manage a local Ollama process."""
from __future__ import annotations

import datetime
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import ClassVar

import requests

from trevvos_forge.runtimes.base import RuntimeActionResult, RuntimeStatus

_START_WAIT_SECONDS = 5
_START_POLL_INTERVAL = 0.5


class OllamaRuntime:
    """Manages a local Ollama process — status, start, and safe stop."""

    name: ClassVar[str] = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: int = 10,
        workspace_root: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.workspace_root = workspace_root

    # ------------------------------------------------------------------
    # State file helpers
    # ------------------------------------------------------------------

    def _state_file(self) -> Path | None:
        if self.workspace_root is None:
            return None
        return self.workspace_root / ".trevvos" / "runtime_state.json"

    def _load_state(self) -> dict | None:
        f = self._state_file()
        if f is None or not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save_state(self, state: dict) -> None:
        f = self._state_file()
        if f is None:
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _clear_state(self) -> None:
        f = self._state_file()
        if f is not None and f.exists():
            try:
                f.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_running(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            resp.raise_for_status()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def status(self) -> RuntimeStatus:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            resp.raise_for_status()
            return RuntimeStatus(
                runtime=self.name,
                is_supported=True,
                is_running=True,
                base_url=self.base_url,
                message="Ollama runtime is reachable.",
            )
        except requests.exceptions.ConnectionError:
            return RuntimeStatus(
                runtime=self.name,
                is_supported=True,
                is_running=False,
                base_url=self.base_url,
                message=f"Ollama runtime is not running at {self.base_url}.",
            )
        except requests.exceptions.Timeout:
            return RuntimeStatus(
                runtime=self.name,
                is_supported=True,
                is_running=None,
                base_url=self.base_url,
                message=f"Ollama runtime timed out at {self.base_url}.",
            )
        except Exception:
            return RuntimeStatus(
                runtime=self.name,
                is_supported=True,
                is_running=None,
                base_url=self.base_url,
                message=f"Could not determine Ollama status at {self.base_url}.",
            )

    def start(self) -> RuntimeActionResult:
        if self._check_running():
            return RuntimeActionResult(
                runtime=self.name,
                action="start",
                status="skipped",
                message="Ollama runtime is already running.",
            )

        ollama_path = shutil.which("ollama")
        if ollama_path is None:
            return RuntimeActionResult(
                runtime=self.name,
                action="start",
                status="failed",
                message="Ollama executable not found. Install Ollama first: https://ollama.com",
            )

        try:
            proc = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return RuntimeActionResult(
                runtime=self.name,
                action="start",
                status="failed",
                message=f"Failed to start Ollama: {exc}",
            )

        self._save_state({
            "runtime": "ollama",
            "managed_by_forge": True,
            "pid": proc.pid,
            "base_url": self.base_url,
            "started_at": datetime.datetime.now().isoformat(),
        })

        deadline = time.time() + _START_WAIT_SECONDS
        while time.time() < deadline:
            if self._check_running():
                return RuntimeActionResult(
                    runtime=self.name,
                    action="start",
                    status="succeeded",
                    message="Ollama runtime started by Trevvos Forge.",
                    details={"pid": proc.pid},
                )
            time.sleep(_START_POLL_INTERVAL)

        return RuntimeActionResult(
            runtime=self.name,
            action="start",
            status="failed",
            message=(
                f"Ollama was started (PID {proc.pid}) but did not become reachable "
                f"within {_START_WAIT_SECONDS}s."
            ),
        )

    def stop(self) -> RuntimeActionResult:
        state = self._load_state()

        if state is None or not state.get("managed_by_forge"):
            return RuntimeActionResult(
                runtime=self.name,
                action="stop",
                status="skipped",
                message="Ollama is running but was not started by Trevvos Forge. Stop it manually.",
            )

        pid = state.get("pid")
        if pid is None:
            self._clear_state()
            return RuntimeActionResult(
                runtime=self.name,
                action="stop",
                status="failed",
                message="Runtime state found but PID is missing.",
            )

        try:
            os.kill(pid, signal.SIGTERM)
            self._clear_state()
            return RuntimeActionResult(
                runtime=self.name,
                action="stop",
                status="succeeded",
                message=f"Ollama runtime (PID {pid}) stopped.",
                details={"pid": pid},
            )
        except ProcessLookupError:
            self._clear_state()
            return RuntimeActionResult(
                runtime=self.name,
                action="stop",
                status="skipped",
                message=f"Ollama runtime (PID {pid}) was already stopped.",
            )
        except PermissionError:
            return RuntimeActionResult(
                runtime=self.name,
                action="stop",
                status="failed",
                message=f"Permission denied when trying to stop Ollama (PID {pid}).",
            )
        except OSError as exc:
            return RuntimeActionResult(
                runtime=self.name,
                action="stop",
                status="failed",
                message=f"Unexpected error stopping Ollama: {exc}",
            )
