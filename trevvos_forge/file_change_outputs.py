import json
from dataclasses import asdict, dataclass
from typing import Any

from trevvos_forge.exceptions import FileChangeOutputError


@dataclass(frozen=True)
class FileChange:
    path: str
    change_type: str
    content: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FileChangesOutput:
    changes: list[FileChange]

    def to_dict(self) -> dict:
        return {
            "changes": [change.to_dict() for change in self.changes],
        }


def parse_file_changes_output(raw_response: str) -> FileChangesOutput:
    json_text = _extract_json_object(raw_response)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise FileChangeOutputError(
            "The model returned invalid JSON for file changes."
        ) from exc

    if not isinstance(data, dict):
        raise FileChangeOutputError("File changes output must be a JSON object.")

    changes = data.get("changes")

    if not isinstance(changes, list):
        raise FileChangeOutputError("Missing or invalid list field: changes")

    if not changes:
        raise FileChangeOutputError("File changes output must contain at least one change.")

    parsed_changes: list[FileChange] = []

    for index, item in enumerate(changes):
        if not isinstance(item, dict):
            raise FileChangeOutputError(
                f"Invalid item at changes[{index}]; expected an object."
            )

        parsed_changes.append(_parse_file_change(item, index))

    return FileChangesOutput(changes=parsed_changes)


def _parse_file_change(data: dict[str, Any], index: int) -> FileChange:
    path = data.get("path")
    change_type = data.get("change_type")
    content = data.get("content")

    if not isinstance(path, str) or not path.strip():
        raise FileChangeOutputError(
            f"Missing or invalid string field: changes[{index}].path"
        )

    if change_type not in {"modified", "created"}:
        raise FileChangeOutputError(
            f"Invalid field changes[{index}].change_type; expected 'modified' or 'created'."
        )

    if not isinstance(content, str):
        raise FileChangeOutputError(
            f"Missing or invalid string field: changes[{index}].content"
        )

    return FileChange(
        path=path.strip(),
        change_type=change_type,
        content=content,
    )


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

    raise FileChangeOutputError(
        "The model response does not contain a valid JSON object."
    )
