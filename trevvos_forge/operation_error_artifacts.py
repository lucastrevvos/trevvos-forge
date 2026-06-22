import re
from dataclasses import asdict, dataclass

from trevvos_forge.sessions import ForgeSession, write_session_json, write_session_text


@dataclass(frozen=True)
class OperationErrorArtifact:
    status: str
    error_type: str
    message: str
    path: str | None
    operation: str | None
    target: str | None
    suggested_resolution: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_operation_error_artifact(message: str) -> OperationErrorArtifact:
    parsed = _parse_operation_target_error(message)

    if parsed is not None:
        operation, error_type, path, target = parsed
        return OperationErrorArtifact(
            status="failed",
            error_type=error_type,
            message=message,
            path=path,
            operation=operation,
            target=target,
            suggested_resolution=_suggested_resolution(error_type),
        )

    mixed_path = _parse_mixed_modes_error(message)

    if mixed_path is not None:
        return OperationErrorArtifact(
            status="failed",
            error_type="mixed_modes",
            message=message,
            path=mixed_path,
            operation=None,
            target=None,
            suggested_resolution=_suggested_resolution("mixed_modes"),
        )

    return OperationErrorArtifact(
        status="failed",
        error_type="operation_error",
        message=message,
        path=None,
        operation=None,
        target=None,
        suggested_resolution=_suggested_resolution("operation_error"),
    )


def write_operation_error_artifacts(session: ForgeSession, message: str) -> OperationErrorArtifact:
    artifact = build_operation_error_artifact(message)
    write_session_json(session, "operation_error.json", artifact.to_dict())
    write_session_text(session, "operation_error.md", render_operation_error_markdown(artifact))
    return artifact


def render_operation_error_markdown(artifact: OperationErrorArtifact) -> str:
    lines = [
        "# Operation Error",
        "",
        f"Status: {artifact.status}",
        f"Error type: {artifact.error_type}",
        "",
        "## Message",
        "",
        artifact.message,
        "",
        "## Details",
        "",
        f"- Path: {artifact.path or 'unknown'}",
        f"- Operation: {artifact.operation or 'unknown'}",
        f"- Target: {artifact.target or 'unknown'}",
        "",
        "## Suggested resolution",
        "",
        artifact.suggested_resolution,
        "",
    ]

    return "\n".join(lines)


def _parse_operation_target_error(message: str) -> tuple[str, str, str, str] | None:
    match = re.match(
        r"Operation (?P<operation>\S+) target (?P<kind>not found|is ambiguous) in (?P<path>[^:]+): (?P<target>.*)",
        message,
        flags=re.DOTALL,
    )

    if match is None:
        return None

    kind = match.group("kind")
    error_type = "target_not_found" if kind == "not found" else "ambiguous_target"

    return (
        match.group("operation"),
        error_type,
        match.group("path").strip(),
        match.group("target"),
    )


def _parse_mixed_modes_error(message: str) -> str | None:
    match = re.match(r"Cannot compose mixed file change modes for: (?P<path>.+)", message)

    if match is None:
        return None

    return match.group("path").strip()


def _suggested_resolution(error_type: str) -> str:
    if error_type == "target_not_found":
        return (
            "Use replace_block or full_file_rewrite for small files, or choose an existing "
            "target from the current file."
        )

    if error_type == "ambiguous_target":
        return (
            "Choose a more specific unique target, use replace_block around a larger block, "
            "or use full_file_rewrite for small files."
        )

    if error_type == "mixed_modes":
        return (
            "Use one edit mode per file. Keep either full_file_rewrite or operation_based_edit "
            "for the path, then regenerate the diff."
        )

    return (
        "Review file_changes.json and choose deterministic operations that match the current "
        "workspace content."
    )
