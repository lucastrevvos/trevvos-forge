import json
from dataclasses import asdict, dataclass
from typing import Any

from trevvos_forge.exceptions import StructuredOutputError


@dataclass(frozen=True)
class PlanOutput:
    summary: str
    project_reading: str
    files_involved: list[str]
    steps: list[str]
    risks: list[str]
    next_command: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanOutput":
        return cls(
            summary=_required_str(data, "summary"),
            project_reading=_required_str(data, "project_reading"),
            files_involved=_required_str_list(data, "files_involved"),
            steps=_required_str_list(data, "steps"),
            risks=_required_str_list(data, "risks"),
            next_command=_required_str(data, "next_command"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        files = "\n".join(f"- {file}" for file in self.files_involved) or "- none"
        steps = "\n".join(f"{index}. {step}" for index, step in enumerate(self.steps, start=1)) or "1. none"
        risks = "\n".join(f"- {risk}" for risk in self.risks) or "- none"

        return f"""# Plan
## Summary

{self.summary}

## Project reading

{self.project_reading}

## Files involved

{files}

## Steps

{steps}

## Risks

{risks}

## Next command

```bash
{self.next_command}
```
""".strip()


def parse_plan_output(raw_response: str) -> PlanOutput:
    json_text = _extract_json_object(raw_response)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(
            "The model returned invalid JSON for the plan output."
        ) from exc

    if not isinstance(data, dict):
        raise StructuredOutputError("The plan output must be a JSON object.")

    return PlanOutput.from_dict(data)


def _extract_json_object(text: str) -> str:
    stripped_text = text.strip()
    decoder = json.JSONDecoder()

    for index, char in enumerate(stripped_text):
        if char != "{":
            continue

        try:
            parsed_value, end_index = decoder.raw_decode(stripped_text[index:])
        except json.JSONDecodeError:
            continue

        if isinstance(parsed_value, dict):
            return stripped_text[index : index + end_index]

    raise StructuredOutputError(
        "The model response does not contain a valid JSON object."
    )


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)

    if not isinstance(value, str) or not value.strip():
        raise StructuredOutputError(f"Missing or invalid string field: {key}")

    return value.strip()


def _required_str_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)

    if not isinstance(value, list):
        raise StructuredOutputError(f"Missing or invalid list field: {key}")

    items: list[str] = []

    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise StructuredOutputError(
                f"Invalid item at {key}[{index}]; expected a non-empty string."
            )

        items.append(item.strip())

    return items
