import json
from datetime import datetime
from pathlib import Path
from typing import Any


TIMELINE_JSONL = "timeline.jsonl"
TIMELINE_MARKDOWN = "timeline.md"
TIMELINE_FIELDS = {
    "timestamp",
    "event",
    "command",
    "status",
    "reason",
    "message",
    "artifacts",
    "next_recommended_command",
}


def append_timeline_event(session_dir: Path, event: dict) -> None:
    payload = _normalize_event(event)
    timeline_path = session_dir / TIMELINE_JSONL

    with timeline_path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        file.write("\n")


def read_timeline(session_dir: Path) -> list[dict]:
    timeline_path = session_dir / TIMELINE_JSONL

    if not timeline_path.exists():
        return []

    events: list[dict] = []

    for line in timeline_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict):
            events.append(payload)

    return events


def render_timeline_markdown(events: list[dict]) -> str:
    lines = ["# Timeline", ""]

    if not events:
        lines.append("- No timeline events recorded.")
        return "\n".join(lines) + "\n"

    for event in events:
        event_name = str(event.get("event") or "unknown")
        status = str(event.get("status") or "unknown")
        timestamp = str(event.get("timestamp") or "unknown time")
        reason = event.get("reason")
        message = event.get("message")
        artifacts = _string_list(event.get("artifacts"))

        line = f"- `{timestamp}` **{event_name}** [{status}]"
        if reason:
            line += f": {reason}"
        if message:
            line += f" - {message}"
        if artifacts:
            line += f" (artifacts: {', '.join(artifacts)})"

        lines.append(line)

    return "\n".join(lines) + "\n"


def write_timeline_markdown(session_dir: Path) -> None:
    events = read_timeline(session_dir)
    (session_dir / TIMELINE_MARKDOWN).write_text(
        render_timeline_markdown(events),
        encoding="utf-8",
    )


def _normalize_event(event: dict) -> dict:
    payload = {
        "timestamp": _timestamp(),
        "event": str(event.get("event") or "event"),
        "command": str(event.get("command") or ""),
        "status": str(event.get("status") or "started"),
        "reason": event.get("reason"),
        "message": event.get("message"),
        "artifacts": _string_list(event.get("artifacts")),
        "next_recommended_command": event.get("next_recommended_command"),
    }

    for key, value in event.items():
        if key in TIMELINE_FIELDS or key == "timestamp":
            continue
        payload[key] = value

    if isinstance(event.get("timestamp"), str) and event["timestamp"].strip():
        payload["timestamp"] = event["timestamp"].strip()

    return payload


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]
