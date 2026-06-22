import re
from dataclasses import asdict, dataclass

from trevvos_forge.sessions import ForgeSession, write_session_json, write_session_text


@dataclass(frozen=True)
class FileChangesErrorArtifact:
    status: str
    error_type: str
    message: str
    raw_response_path: str
    suggested_resolution: str
    operation: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def build_file_changes_error_artifact(message: str) -> FileChangesErrorArtifact:
    error_type = _error_type(message)
    operation = _operation(message) if error_type == "unknown_operation" else None
    return FileChangesErrorArtifact(
        status="failed",
        error_type=error_type,
        message=message,
        raw_response_path="file_changes_raw_response.json",
        suggested_resolution=_suggested_resolution(error_type, operation),
        operation=operation,
    )


def write_file_changes_error_artifacts(session: ForgeSession, message: str) -> FileChangesErrorArtifact:
    artifact = build_file_changes_error_artifact(message)
    write_session_json(session, "file_changes_error.json", artifact.to_dict())
    write_session_text(session, "file_changes_error.md", render_file_changes_error_markdown(artifact))
    return artifact


def render_file_changes_error_markdown(artifact: FileChangesErrorArtifact) -> str:
    return "\n".join(
        [
            "# File Changes Error",
            "",
            "The model response could not be parsed as valid file changes.",
            "",
            "## Error",
            "",
            artifact.message,
            "",
            "## Suggested resolution",
            "",
            "Run:",
            "",
            "```bash",
            "trevvos diff --retry",
            "```",
            "",
        ]
    )


def _error_type(message: str) -> str:
    if "Missing or invalid list field: changes" in message:
        return "invalid_file_changes_schema"

    if "full_file_rewrite must be used as mode with content" in message:
        return "invalid_file_changes_schema"

    if "Unknown operation at changes" in message:
        return "unknown_operation"

    return "invalid_file_changes_output"


def _operation(message: str) -> str | None:
    match = re.search(r"Unknown operation at changes\[\d+\]\.operation: ([^.]+)", message)
    if match is None:
        return None
    return match.group(1).strip()


def _suggested_resolution(error_type: str, operation: str | None) -> str:
    if error_type == "unknown_operation":
        if operation == "full_file_rewrite":
            return (
                "Use mode: full_file_rewrite with content, or choose one of the "
                "allowed operation_based_edit operations."
            )
        return "Choose one of the allowed operation_based_edit operations and regenerate the diff."

    return "Run trevvos diff --retry to regenerate file changes using the expected schema."
