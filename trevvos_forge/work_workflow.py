from trevvos_forge.sessions import ForgeSession, write_session_json, write_session_text


def build_work_metadata(
    *,
    request: str,
    status: str,
    max_retries: int,
    max_repairs: int,
    retries_used: int,
    repairs_used: int,
    max_plan_retries: int | None = None,
    plan_retries_used: int = 0,
    final_phase: str,
    next_command: str | None,
    steps: list[dict],
    reason: str | None = None,
) -> dict:
    metadata = {
        "status": status,
        "request": request,
        "max_retries": max_retries,
        "max_repairs": max_repairs,
        "max_plan_retries": max_plan_retries if max_plan_retries is not None else max_retries,
        "retries_used": retries_used,
        "repairs_used": repairs_used,
        "plan_retries_used": plan_retries_used,
        "final_phase": final_phase,
        "next_command": next_command,
        "steps": steps,
    }

    if reason:
        metadata["reason"] = reason

    return metadata


def render_work_summary(metadata: dict) -> str:
    request = metadata.get("request") or ""
    final_status = _status_text(str(metadata.get("status") or "unknown"))
    steps = metadata.get("steps")
    next_command = metadata.get("next_command")
    reason = metadata.get("reason")

    lines = [
        "# Work Summary",
        "",
        "## Request",
        "",
        str(request),
        "",
        "## Final status",
        "",
        final_status,
    ]

    if reason:
        lines.extend(["", "## Reason", "", str(reason)])

    lines.extend(["", "## Steps"])

    if isinstance(steps, list) and steps:
        for step in steps:
            if not isinstance(step, dict):
                continue
            label = str(step.get("step") or "step").replace("_", " ").title()
            status = str(step.get("status") or "unknown")
            step_reason = step.get("reason")
            suffix = f" due to {step_reason}" if step_reason else ""
            lines.append(f"- {label} {status}{suffix}.")
    else:
        lines.append("- None.")

    lines.extend(["", "## Next", ""])

    if next_command:
        lines.extend(["Run:", "", "```bash", str(next_command), "```"])
    else:
        lines.append("No next command.")

    return "\n".join(lines).rstrip() + "\n"


def write_work_artifacts(session: ForgeSession, metadata: dict) -> None:
    write_session_json(session, "work_metadata.json", metadata)
    write_session_text(session, "work_summary.md", render_work_summary(metadata))


def _status_text(status: str) -> str:
    if status == "ready_to_apply":
        return "Ready to apply."
    if status == "blocked":
        return "Blocked."
    if status == "failed":
        return "Failed."
    return status.replace("_", " ").title() + "."
