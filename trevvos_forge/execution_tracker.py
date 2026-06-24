"""ExecutionTracker — per-stage and total timing for long-running workflows."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


def format_duration(seconds: float) -> str:
    """Return human-readable duration string, e.g. '1.23s'."""
    return f"{seconds:.2f}s"


class CommandTimer:
    """Lightweight timer for total CLI command duration.

    Usage::

        timer = CommandTimer()
        # ... do work ...
        print(f"Duration: {timer.format()}")
        metadata["duration_seconds"] = timer.duration_seconds
    """

    def __init__(self) -> None:
        self._start = time.perf_counter()

    @property
    def duration_seconds(self) -> float:
        return round(time.perf_counter() - self._start, 2)

    def format(self) -> str:
        return format_duration(self.duration_seconds)

    def to_dict(self) -> dict[str, float]:
        return {"duration_seconds": self.duration_seconds}


@dataclass
class ExecutionStage:
    name: str
    label: str
    status: str = "running"
    duration_seconds: float | None = None
    error: str | None = None
    _start: float = field(default_factory=time.perf_counter, repr=False, compare=False)


class ExecutionTracker:
    """Tracks execution stages and total workflow duration.

    Usage::

        tracker = ExecutionTracker()
        tracker.start_stage("generate", "Generating tests")
        # ... do work ...
        tracker.finish_stage("generate")
        data = tracker.to_dict()
    """

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._stages: list[ExecutionStage] = []
        self._stage_map: dict[str, ExecutionStage] = {}

    def start_stage(self, name: str, label: str) -> None:
        stage = ExecutionStage(name=name, label=label)
        self._stages.append(stage)
        self._stage_map[name] = stage

    def finish_stage(self, name: str, status: str = "passed") -> None:
        stage = self._stage_map[name]
        elapsed = time.perf_counter() - stage._start
        stage.status = status
        stage.duration_seconds = round(elapsed, 3)

    def fail_stage(self, name: str, error: str = "") -> None:
        stage = self._stage_map[name]
        elapsed = time.perf_counter() - stage._start
        stage.status = "failed"
        stage.duration_seconds = round(elapsed, 3)
        if error:
            stage.error = error

    def total_duration(self) -> float:
        return round(time.perf_counter() - self._start, 3)

    def to_dict(self) -> dict[str, Any]:
        total = self.total_duration()
        stages = []
        for s in self._stages:
            entry: dict[str, Any] = {
                "name": s.name,
                "label": s.label,
                "status": s.status,
                "duration_seconds": s.duration_seconds,
            }
            if s.error:
                entry["error"] = s.error
            stages.append(entry)
        return {
            "duration_seconds": total,
            "stages": stages,
        }
