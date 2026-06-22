import re
from pathlib import Path
from typing import Any

from trevvos_forge.sessions import ForgeSession, write_session_json


COMMAND_PATTERNS = [
    re.compile(r"`([^`]+)`"),
    re.compile(r"((?:python|py)\s+[^\n`]+)", re.IGNORECASE),
]

STOP_MARKERS = [
    " prints ",
    " print ",
    " should print ",
    " deve imprimir ",
    " imprime ",
    " exits ",
    " exit ",
    " -> ",
]


def extract_command_like_expected_behaviors(plan: dict) -> list[str]:
    expected = plan.get("expected_behavior") if isinstance(plan, dict) else None
    if not isinstance(expected, list):
        return []

    commands: list[str] = []
    for item in expected:
        if not isinstance(item, str):
            continue
        command = _extract_command(item)
        if command:
            commands.append(command)

    return _dedupe(commands)


def check_plan_verification_coverage(plan: dict) -> dict:
    expected_commands = extract_command_like_expected_behaviors(plan)
    suggested = _string_list(plan.get("suggested_verification_commands") if isinstance(plan, dict) else None)
    covered: list[str] = []
    missing: list[str] = []

    for expected in expected_commands:
        if any(_commands_compatible(expected, command) for command in suggested):
            covered.append(expected)
        else:
            missing.append(expected)

    warnings = [
        f"Expected behavior command `{command}` is not covered by suggested verification commands."
        for command in missing
    ]

    status = "passed"
    if missing:
        status = "failed"
    elif expected_commands and not suggested:
        status = "failed"
    elif not expected_commands:
        status = "passed"

    return {
        "status": status,
        "expected_behavior_commands": expected_commands,
        "suggested_verification_commands": suggested,
        "covered": covered,
        "missing": missing,
        "warnings": warnings,
    }


def write_verification_coverage(session: ForgeSession, plan: dict) -> dict:
    result = check_plan_verification_coverage(plan)
    write_session_json(session, "verification_coverage.json", result)
    return result


def has_failed_verification_coverage(session_dir: Path) -> bool:
    payload = _read_json(session_dir / "verification_coverage.json")
    return isinstance(payload, dict) and payload.get("status") == "failed"


def high_risk_warnings(warnings_payload: Any) -> list[str]:
    warnings = []
    if isinstance(warnings_payload, dict) and isinstance(warnings_payload.get("warnings"), list):
        warnings = warnings_payload["warnings"]
    elif isinstance(warnings_payload, list):
        warnings = warnings_payload

    return [
        warning
        for warning in warnings
        if isinstance(warning, str) and _is_high_risk_warning(warning)
    ]


def _extract_command(text: str) -> str | None:
    stripped = text.strip()
    if not _looks_command_like(stripped):
        return None

    for pattern in COMMAND_PATTERNS:
        match = pattern.search(stripped)
        if match:
            return _trim_command(match.group(1))

    return None


def _looks_command_like(text: str) -> bool:
    lowered = text.lower()
    return (
        lowered.startswith("python ")
        or lowered.startswith("py ")
        or "python main.py" in lowered
        or "->" in lowered
        or " prints " in lowered
        or " deve imprimir " in lowered
        or " should print " in lowered
        or "`" in lowered
    )


def _trim_command(command: str) -> str:
    trimmed = command.strip().strip(".")
    lowered = f" {trimmed.lower()} "
    cut_index = len(trimmed)
    for marker in STOP_MARKERS:
        index = lowered.find(marker)
        if index >= 0:
            cut_index = min(cut_index, index)
    return trimmed[:cut_index].strip().strip(".")


def _commands_compatible(expected: str, suggested: str) -> bool:
    expected_tokens = _normalize_command(expected)
    suggested_tokens = _normalize_command(suggested)
    if not expected_tokens or not suggested_tokens:
        return False
    if len(suggested_tokens) < len(expected_tokens):
        return False
    return suggested_tokens[: len(expected_tokens)] == expected_tokens


def _normalize_command(command: str) -> list[str]:
    tokens = re.findall(r'"[^"]+"|\'[^\']+\'|\S+', command)
    normalized: list[str] = []
    for token in tokens:
        cleaned = token.strip().strip('"').strip("'")
        lowered = cleaned.lower().replace("\\", "/")
        if lowered.endswith("/python.exe") or lowered.endswith("/python") or lowered in {"python.exe", "python", "py"}:
            normalized.append("python")
        else:
            normalized.append(lowered)
    return normalized


def _is_high_risk_warning(warning: str) -> bool:
    return "small file structural edit risk" in warning.lower()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
