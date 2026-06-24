"""Progress reporter for long-running CLI commands."""
from __future__ import annotations

import sys
from typing import Any


class NoopProgressReporter:
    """Reporter that silently discards all progress events."""

    def start_stage(self, label: str) -> None:
        pass

    def finish_stage(self) -> None:
        pass

    def fail_stage(self) -> None:
        pass

    def __enter__(self) -> "NoopProgressReporter":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class RichProgressReporter:
    """Reporter that updates a Rich spinner with per-stage labels."""

    def __init__(self, console: Any) -> None:
        self._console = console
        self._status: Any = None

    def __enter__(self) -> "RichProgressReporter":
        self._status = self._console.status("", spinner="dots")
        self._status.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._status is not None:
            self._status.__exit__(*args)

    def start_stage(self, label: str) -> None:
        if self._status is not None:
            self._status.update(f"[bold]{label}[/bold]")

    def finish_stage(self) -> None:
        pass

    def fail_stage(self) -> None:
        pass


def build_progress_reporter(
    *, enabled: bool, console: Any | None = None
) -> NoopProgressReporter | RichProgressReporter:
    """Return a RichProgressReporter when enabled and console is provided, else Noop."""
    if not enabled or console is None:
        return NoopProgressReporter()
    try:
        return RichProgressReporter(console)
    except Exception:
        return NoopProgressReporter()
