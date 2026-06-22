from dataclasses import dataclass

from trevvos_forge.sessions import ForgeSession, write_session_json, write_session_text


RAW_PLAN_RESPONSE_PATH = "plan_raw_response.md"


@dataclass(frozen=True)
class PlanErrorArtifact:
    status: str
    error_type: str
    message: str
    raw_response_path: str
    suggested_resolution: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "error_type": self.error_type,
            "message": self.message,
            "raw_response_path": self.raw_response_path,
            "suggested_resolution": self.suggested_resolution,
        }


def build_plan_error_artifact(message: str) -> PlanErrorArtifact:
    error_type = classify_plan_error(message)
    return PlanErrorArtifact(
        status="failed",
        error_type=error_type,
        message=message,
        raw_response_path=RAW_PLAN_RESPONSE_PATH,
        suggested_resolution=(
            "Run trevvos plan --retry or rerun trevvos work. "
            "The model must return a valid JSON object matching plan_change_json."
        ),
    )


def classify_plan_error(message: str) -> str:
    normalized = message.lower()
    if "does not contain a valid json object" in normalized:
        return "invalid_plan_json"
    if "invalid json" in normalized:
        return "invalid_plan_json"
    if "json object" in normalized and "must be" in normalized:
        return "invalid_plan_json"
    return "invalid_plan_schema"


def write_plan_error_artifacts(session: ForgeSession, message: str) -> PlanErrorArtifact:
    artifact = build_plan_error_artifact(message)
    write_session_json(session, "plan_error.json", artifact.to_dict())
    write_session_text(session, "plan_error.md", render_plan_error_markdown(artifact))
    return artifact


def render_plan_error_markdown(artifact: PlanErrorArtifact) -> str:
    return f"""# Plan Error

The model response could not be parsed as a valid plan.

## Error

{artifact.message}

## Suggested resolution

Run:

```bash
trevvos plan --retry
```
""".strip() + "\n"
