"""
Advisory workflow helpers — shared logic for advisory commands.

The CLI owns settings, provider construction, context building, and output
rendering. This module owns the provider call, artifact writing, metadata
persistence, session update, and timeline recording.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trevvos_forge.sessions import ForgeSession, update_session_status, write_session_json, write_session_text
from trevvos_forge.timeline import append_timeline_event, write_timeline_markdown


@dataclass(frozen=True)
class AdvisoryProviderCallRequest:
    prompt: str
    prompt_artifact_name: str
    response_artifact_names: list[str]
    metadata: dict[str, Any]
    metadata_artifact_name: str
    completed_status: str
    completed_event: str
    timeline_command: str
    timeline_artifacts: list[str]


@dataclass(frozen=True)
class AdvisoryProviderCallResult:
    raw_response: str
    session: ForgeSession
    metadata: dict[str, Any]


def run_advisory_provider_call(
    *,
    session: ForgeSession,
    provider: Any,
    request: AdvisoryProviderCallRequest,
) -> AdvisoryProviderCallResult:
    """
    Write prompt artifact, call provider, write response artifacts, persist
    metadata, update session status, and record timeline.
    """
    write_session_text(session=session, file_name=request.prompt_artifact_name, content=request.prompt)
    raw_response = provider.generate(request.prompt)
    for artifact_name in request.response_artifact_names:
        write_session_text(session=session, file_name=artifact_name, content=raw_response)
    write_session_json(session, request.metadata_artifact_name, request.metadata)
    updated_session = update_session_status(session, request.completed_status)
    record_advisory_timeline_event(
        updated_session,
        request.completed_event,
        request.timeline_command,
        "succeeded",
        artifacts=request.timeline_artifacts,
    )
    return AdvisoryProviderCallResult(
        raw_response=raw_response,
        session=updated_session,
        metadata=request.metadata,
    )


def write_advisory_failure_metadata(
    *,
    session: ForgeSession | None,
    metadata_artifact_name: str,
    metadata: dict[str, Any],
    failed_event: str,
    timeline_command: str,
    message: str,
) -> None:
    """Write error metadata and record a failed timeline event."""
    if session is None:
        return
    try:
        write_session_json(session, metadata_artifact_name, metadata)
        record_advisory_timeline_event(
            session,
            failed_event,
            timeline_command,
            "failed",
            message=message,
            artifacts=[metadata_artifact_name],
        )
    except Exception:
        return


def record_advisory_timeline_event(
    session: ForgeSession | None,
    event: str,
    command: str,
    status: str,
    **fields: Any,
) -> None:
    if session is None:
        return
    try:
        payload = {
            "event": event,
            "command": command,
            "status": status,
            "session_id": session.metadata.id,
            **fields,
        }
        append_timeline_event(session.path, payload)
        write_timeline_markdown(session.path)
    except Exception:
        return
