import json
from dataclasses import asdict, dataclass
from typing import Any

from trevvos_forge.exceptions import FileChangeOutputError


ALLOWED_OPERATION_BASED_EDIT_OPERATIONS = {
    "insert_after_heading",
    "insert_after_line",
    "insert_before_line",
    "replace_exact_text",
    "replace_block",
    "append_to_file",
    "create_file",
}


@dataclass(frozen=True)
class FileChange:
    path: str
    change_type: str
    content: str | None
    mode: str
    operation: str | None = None
    target: str | None = None
    insert: str | None = None
    replacement: str | None = None

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

    error = data.get("error")

    if isinstance(error, str) and error.strip():
        raise FileChangeOutputError(f"The model could not produce safe file changes: {error.strip()}")

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
    mode = data.get("mode", "full_file_rewrite")
    operation = data.get("operation")
    target = data.get("target")
    insert = data.get("insert")
    replacement = data.get("replacement")

    if not isinstance(path, str) or not path.strip():
        raise FileChangeOutputError(
            f"Missing or invalid string field: changes[{index}].path"
        )

    if change_type not in {"modified", "created"}:
        raise FileChangeOutputError(
            f"Invalid field changes[{index}].change_type; expected 'modified' or 'created'."
        )

    if operation == "full_file_rewrite":
        if not isinstance(content, str):
            raise FileChangeOutputError(
                "full_file_rewrite must be used as mode with content, not as an operation."
            )
        if any(isinstance(data.get(field), str) and data.get(field).strip() for field in ["target", "insert", "replacement"]):
            raise FileChangeOutputError(
                "full_file_rewrite must be used as mode with content, not as an operation."
            )
        mode = "full_file_rewrite"
        operation = None
        target = None
        insert = None
        replacement = None

    if mode not in {"full_file_rewrite", "operation_based_edit"}:
        raise FileChangeOutputError(
            f"Invalid field changes[{index}].mode; expected 'full_file_rewrite' or 'operation_based_edit'."
        )

    if mode == "full_file_rewrite":
        if not isinstance(content, str):
            raise FileChangeOutputError(
                f"Missing or invalid string field: changes[{index}].content"
            )
    else:
        _validate_operation_fields(
            index=index,
            change_type=change_type,
            operation=operation,
            target=target,
            insert=insert,
            replacement=replacement,
            content=content,
        )

    return FileChange(
        path=path.strip(),
        change_type=change_type,
        content=content if isinstance(content, str) else None,
        mode=mode,
        operation=operation if isinstance(operation, str) else None,
        target=target if isinstance(target, str) else None,
        insert=insert if isinstance(insert, str) else None,
        replacement=replacement if isinstance(replacement, str) else None,
    )


def _validate_operation_fields(
    *,
    index: int,
    change_type: str,
    operation: Any,
    target: Any,
    insert: Any,
    replacement: Any,
    content: Any,
) -> None:
    if not isinstance(operation, str):
        raise FileChangeOutputError(
            f"Missing or invalid string field: changes[{index}].operation"
        )

    if operation == "insert_after_heading":
        if change_type != "modified":
            raise FileChangeOutputError(
                f"Operation changes[{index}].operation requires change_type 'modified'."
            )
        _require_operation_str(index, "target", target)
        _require_operation_str(index, "insert", insert)
        return

    if operation == "insert_after_line":
        if change_type != "modified":
            raise FileChangeOutputError(
                f"Operation changes[{index}].operation requires change_type 'modified'."
            )
        _require_operation_str(index, "target", target)
        _require_operation_str(index, "insert", insert)
        return

    if operation == "insert_before_line":
        if change_type != "modified":
            raise FileChangeOutputError(
                f"Operation changes[{index}].operation requires change_type 'modified'."
            )
        _require_operation_str(index, "target", target)
        _require_operation_str(index, "insert", insert)
        return

    if operation == "replace_exact_text":
        if change_type != "modified":
            raise FileChangeOutputError(
                f"Operation changes[{index}].operation requires change_type 'modified'."
            )
        _require_operation_str(index, "target", target)
        _require_operation_str(index, "replacement", replacement)
        return

    if operation == "replace_block":
        if change_type != "modified":
            raise FileChangeOutputError(
                f"Operation changes[{index}].operation requires change_type 'modified'."
            )
        _require_operation_str(index, "target", target)
        _require_operation_str(index, "replacement", replacement)
        return

    if operation == "append_to_file":
        if change_type != "modified":
            raise FileChangeOutputError(
                f"Operation changes[{index}].operation requires change_type 'modified'."
            )
        _require_operation_str(index, "insert", insert)
        return

    if operation == "create_file":
        if change_type != "created":
            raise FileChangeOutputError(
                f"Operation changes[{index}].operation requires change_type 'created'."
            )
        if not isinstance(content, str):
            raise FileChangeOutputError(
                f"Missing or invalid string field: changes[{index}].content"
            )
        return

    allowed = ", ".join(sorted(ALLOWED_OPERATION_BASED_EDIT_OPERATIONS))
    raise FileChangeOutputError(
        f"Unknown operation at changes[{index}].operation: {operation}. Allowed operation_based_edit operations: {allowed}."
    )


def _require_operation_str(index: int, field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise FileChangeOutputError(
            f"Missing or invalid string field: changes[{index}].{field_name}"
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
