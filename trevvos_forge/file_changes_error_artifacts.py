from dataclasses import asdict, dataclass

from trevvos_forge.sessions import ForgeSession, write_session_json, write_session_text


@dataclass(frozen=True)
class FileChangesErrorArtifact:
    status: str
    error_type: str
    message: str
    raw_response_path: str
    suggested_resolution: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_file_changes_error_artifact(message: str) -> FileChangesErrorArtifact:
    return FileChangesErrorArtifact(
        status="failed",
        error_type=_error_type(message),
        message=message,
        raw_response_path="file_changes_raw_response.json",
        suggested_resolution=(
            "Run trevvos diff --retry to regenerate file changes using the expected schema."
        ),
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

    return "invalid_file_changes_output"
