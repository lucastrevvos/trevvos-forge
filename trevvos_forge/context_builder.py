import json
from dataclasses import asdict, dataclass
from pathlib import Path

from trevvos_forge.workspace import (
    ProjectFile,
    ProjectScanResult,
    read_workspace_file,
    scan_workspace,
)


DEFAULT_MAX_FILES = 8
DEFAULT_MAX_TOTAL_CHARS = 30_000
DEFAULT_MAX_CHARS_PER_FILE = 8_000


HIGH_VALUE_FILES = {
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "tsconfig.json",
    "angular.json",
    "Dockerfile",
    "docker-compose.yml",
    "Program.cs",
    "appsettings.json",
}


CODE_EXTENSIONS = {
    ".py",
    ".cs",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
}


@dataclass(frozen=True)
class ContextFile:
    path: str
    size_bytes: int
    score: int
    reason: str
    content: str


@dataclass(frozen=True)
class BuiltContext:
    instruction: str
    workspace_root: str
    selected_files: list[ContextFile]
    total_chars: int

    def to_markdown(self) -> str:
        files_block = []

        for selected_file in self.selected_files:
            files_block.append(
                f"""## File: {selected_file.path}

Reason: {selected_file.reason}
Score: {selected_file.score}
Size: {selected_file.size_bytes} bytes

```text
{selected_file.content}
```"""
            )

        files_markdown = "\n\n".join(files_block) if files_block else "No files selected."

        return f"""# Trevvos Forge Context

## User request

{self.instruction}

## Workspace

{self.workspace_root}

## Selected files

{", ".join(file.path for file in self.selected_files) if self.selected_files else "none"}

## File contents

{files_markdown}
""".strip()

    def selected_files_json(self) -> str:
        payload = {
            "instruction": self.instruction,
            "workspace_root": self.workspace_root,
            "total_chars": self.total_chars,
            "selected_files": [
                {
                    "path": file.path,
                    "size_bytes": file.size_bytes,
                    "score": file.score,
                    "reason": file.reason,
                }
                for file in self.selected_files
            ],
        }

        return json.dumps(payload, indent=2, ensure_ascii=False)


def build_context(
    root: Path,
    instruction: str,
    max_files: int = DEFAULT_MAX_FILES,
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
    max_chars_per_file: int = DEFAULT_MAX_CHARS_PER_FILE,
) -> BuiltContext:
    scan_result = scan_workspace(root=root, max_files=300)
    candidates = _rank_files(scan_result=scan_result, instruction=instruction)

    selected_files: list[ContextFile] = []
    total_chars = 0

    for candidate in candidates:
        if len(selected_files) >= max_files:
            break

        if total_chars >= max_total_chars:
            break

        remaining_chars = max_total_chars - total_chars
        file_char_limit = min(max_chars_per_file, remaining_chars)

        if file_char_limit <= 0:
            break

        try:
            content = read_workspace_file(
                root=root,
                file_path=Path(candidate.path),
                max_chars=file_char_limit,
            )
        except Exception:
            continue

        if len(content) > file_char_limit:
            content = _truncate_to_limit(content, file_char_limit)

        total_chars += len(content)

        selected_files.append(
            ContextFile(
                path=candidate.path,
                size_bytes=candidate.size_bytes,
                score=_score_file(candidate, instruction),
                reason=_reason_for_file(candidate, instruction),
                content=content,
            )
        )

    return BuiltContext(
        instruction=instruction,
        workspace_root=scan_result.root,
        selected_files=selected_files,
        total_chars=total_chars,
    )


def _truncate_to_limit(content: str, max_chars: int) -> str:
    marker = "\n\n[... truncated by Trevvos Forge ...]"

    if max_chars <= 0:
        return ""

    if len(content) <= max_chars:
        return content

    if max_chars <= len(marker):
        return content[:max_chars]

    return content[: max_chars - len(marker)] + marker


def _rank_files(scan_result: ProjectScanResult, instruction: str) -> list[ProjectFile]:
    return sorted(
        scan_result.files,
        key=lambda file: _score_file(file, instruction),
        reverse=True,
    )


def _path_has_token(path: str, expected_token: str) -> bool:
    normalized_path = path.lower().replace("\\", "/")
    tokens: set[str] = set()

    for part in normalized_path.split("/"):
        cleaned_part = (
            part.replace(".", "_")
            .replace("-", "_")
            .replace(" ", "_")
        )

        for token in cleaned_part.split("_"):
            if token:
                tokens.add(token)

    return expected_token.lower() in tokens


def _score_file(file: ProjectFile, instruction: str) -> int:
    instruction_lower = instruction.lower()
    path_lower = file.path.lower()
    file_name = Path(file.path).name

    score = 0

    if file_name in HIGH_VALUE_FILES:
        score += 40

    if file.extension in CODE_EXTENSIONS:
        score += 20

    if "test" in instruction_lower or "teste" in instruction_lower:
        if "test" in path_lower or "tests" in path_lower:
            score += 45
        if "pytest" in path_lower:
            score += 20
        if file_name == "pyproject.toml":
            score += 35

    if "cli" in instruction_lower or "comando" in instruction_lower or "command" in instruction_lower:
        if _path_has_token(file.path, "cli"):
            score += 50
        if file_name == "pyproject.toml":
            score += 25
        if file_name == "README.md":
            score += 20

    if "config" in instruction_lower or "settings" in instruction_lower or "configuração" in instruction_lower:
        if "settings" in path_lower or "config" in path_lower:
            score += 50

    if "readme" in instruction_lower or "document" in instruction_lower or "documentação" in instruction_lower:
        if file_name == "README.md":
            score += 60

    if "python" in instruction_lower and file.extension == ".py":
        score += 15

    if "c#" in instruction_lower or "csharp" in instruction_lower or ".net" in instruction_lower:
        if file.extension == ".cs" or file.path.endswith(".csproj"):
            score += 30

    # Prefer smaller files for early MVP context.
    if file.size_bytes <= 12_000:
        score += 10
    elif file.size_bytes > 80_000:
        score -= 30

    return score


def _reason_for_file(file: ProjectFile, instruction: str) -> str:
    instruction_lower = instruction.lower()
    path_lower = file.path.lower()
    file_name = Path(file.path).name

    reasons: list[str] = []

    if file_name in HIGH_VALUE_FILES:
        reasons.append("high-value project file")

    if file.extension in CODE_EXTENSIONS:
        reasons.append("source code file")

    if (
        "cli" in instruction_lower or "comando" in instruction_lower
    ) and _path_has_token(file.path, "cli"):
        reasons.append("matches CLI-related request")

    if ("test" in instruction_lower or "teste" in instruction_lower) and "test" in path_lower:
        reasons.append("matches test-related request")

    if ("config" in instruction_lower or "settings" in instruction_lower) and (
        "settings" in path_lower or "config" in path_lower
    ):
        reasons.append("matches configuration-related request")

    if not reasons:
        reasons.append("ranked by project context heuristic")

    return ", ".join(reasons)
