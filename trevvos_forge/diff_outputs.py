from trevvos_forge.exceptions import DiffError


def extract_unified_diff(raw_response: str) -> str:
    cleaned = raw_response.strip()

    if cleaned.startswith("```"):
        cleaned = _strip_markdown_fence(cleaned)

    diff_start = cleaned.find("diff --git ")

    if diff_start == -1:
        diff_start = cleaned.find("--- ")

    if diff_start > 0:
        cleaned = cleaned[diff_start:].strip()

    if not cleaned:
        raise DiffError("The model returned an empty diff response.")

    if not _looks_like_diff(cleaned):
        raise DiffError("The model response does not look like a unified diff.")

    return cleaned


def _strip_markdown_fence(text: str) -> str:
    lines = text.splitlines()

    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]

    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    return "\n".join(lines).strip()


def _looks_like_diff(text: str) -> bool:
    return (
        "diff --git " in text
        or ("--- " in text and "+++ " in text)
        or "@@ " in text
    )
