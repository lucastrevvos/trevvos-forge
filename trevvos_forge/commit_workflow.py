import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from trevvos_forge.exceptions import CommitError


@dataclass(frozen=True)
class GitStatusEntry:
    path: str
    index_status: str
    worktree_status: str
    raw: str

    @property
    def is_staged(self) -> bool:
        return self.index_status not in {" ", "?"}


@dataclass(frozen=True)
class GitStatus:
    entries: list[GitStatusEntry]

    @property
    def staged_paths(self) -> list[str]:
        return [entry.path for entry in self.entries if entry.is_staged]

    @property
    def changed_paths(self) -> list[str]:
        return [entry.path for entry in self.entries]


@dataclass(frozen=True)
class CommitMessage:
    subject: str
    body: list[str]
    confidence: str = "medium"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CommitPlan:
    session_id: str
    mode: str
    files_to_stage: list[str]
    unrelated_changes: list[str]
    test_status: str | None
    sandbox_test_status: str | None
    working_tree_test_status: str | None
    review_verdict: str | None
    review_risk_level: str | None
    message: CommitMessage

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "files_to_stage": self.files_to_stage,
            "unrelated_changes": self.unrelated_changes,
            "test_status": self.test_status,
            "sandbox_test_status": self.sandbox_test_status,
            "working_tree_test_status": self.working_tree_test_status,
            "review_verdict": self.review_verdict,
            "review_risk_level": self.review_risk_level,
            "message": self.message.to_dict(),
        }


@dataclass(frozen=True)
class CommitResult:
    status: str
    commit_hash: str | None = None
    files_staged: list[str] | None = None
    message_subject: str | None = None
    error: str | None = None
    exit_code: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def extract_patch_paths(patch_text: str) -> list[str]:
    paths: list[str] = []

    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()

            if len(parts) >= 4:
                path = _normalize_patch_path(parts[3])

                if path and path not in paths:
                    paths.append(path)

        elif line.startswith("+++ "):
            path = _normalize_patch_path(line[4:].strip())

            if path and path not in paths:
                paths.append(path)

    return paths


def get_git_status(repo_root: Path) -> GitStatus:
    result = _run_git(repo_root, ["status", "--porcelain"])

    if result.returncode != 0:
        raise CommitError(f"git status failed: {result.stderr.strip() or result.stdout.strip()}")

    entries = []

    for line in result.stdout.splitlines():
        if not line.strip():
            continue

        entry = _parse_status_line(line)

        if entry.path == ".trevvos" or entry.path.startswith(".trevvos/"):
            continue

        entries.append(entry)

    return GitStatus(entries=entries)


def build_commit_plan(
    *,
    session_dir: Path,
    repo_root: Path,
    message: CommitMessage | None = None,
    mode: str = "deterministic",
) -> CommitPlan:
    metadata = _read_json(session_dir / "metadata.json")
    session_id = str(metadata.get("id", "unknown")) if isinstance(metadata, dict) else "unknown"
    patch_path = session_dir / "diff.patch"

    if not patch_path.exists():
        raise CommitError("Cannot commit: diff.patch not found in session.")

    related_paths = extract_patch_paths(patch_path.read_text(encoding="utf-8"))

    if not related_paths:
        raise CommitError("Cannot commit: no related files were found in diff.patch.")

    status = get_git_status(repo_root)

    if status.staged_paths:
        raise CommitError(
            "Cannot commit: staged changes already exist. "
            "Commit, unstage, or stash them before running trevvos commit."
        )

    changed_paths = set(status.changed_paths)
    related_set = set(related_paths)
    files_to_stage = sorted(path for path in related_paths if path in changed_paths)
    unrelated_changes = sorted(path for path in changed_paths if path not in related_set)

    if not files_to_stage:
        raise CommitError("Cannot commit: no related session files are modified in the working tree.")

    commit_message = message or build_deterministic_commit_message(session_dir, files_to_stage)

    return CommitPlan(
        session_id=session_id,
        mode=mode,
        files_to_stage=files_to_stage,
        unrelated_changes=unrelated_changes,
        test_status=_test_status(session_dir),
        sandbox_test_status=_mode_specific_test_status(session_dir, "sandbox"),
        working_tree_test_status=_mode_specific_test_status(session_dir, "working_tree"),
        review_verdict=_review_field(session_dir, "verdict"),
        review_risk_level=_review_field(session_dir, "risk_level"),
        message=commit_message,
    )


def build_deterministic_commit_message(session_dir: Path, files: list[str]) -> CommitMessage:
    change_summary = _read_text(session_dir / "change_summary.md")
    file_changes = _read_json(session_dir / "file_changes.json")
    subject = _subject_from_change_summary(change_summary)

    if not subject:
        subject = _subject_from_file_changes(file_changes, files)

    body = []

    if files:
        body.append("Updates files from the current Trevvos Forge session.")

    return CommitMessage(
        subject=_clean_subject(subject or "Update project files"),
        body=body,
        confidence="medium",
    )


def parse_commit_message_response(text: str) -> CommitMessage:
    try:
        payload = _extract_json_object(text)
    except ValueError as exc:
        raise CommitError(str(exc)) from exc

    if not isinstance(payload, dict):
        raise CommitError("Commit message response must be a JSON object.")

    subject = payload.get("subject")

    if not isinstance(subject, str) or not subject.strip():
        raise CommitError("Commit message response is missing subject.")

    raw_body = payload.get("body", [])
    body = [line for line in raw_body if isinstance(line, str)] if isinstance(raw_body, list) else []
    confidence = payload.get("confidence") if isinstance(payload.get("confidence"), str) else "medium"

    return CommitMessage(
        subject=_clean_subject(subject),
        body=body,
        confidence=confidence,
    )


def render_commit_message(message: CommitMessage) -> str:
    subject = _clean_subject(message.subject)

    if not message.body:
        return subject + "\n"

    body = "\n".join(line.strip() for line in message.body if line.strip())

    if not body:
        return subject + "\n"

    return f"{subject}\n\n{body}\n"


def write_commit_artifacts(
    *,
    session_dir: Path,
    plan: CommitPlan,
    result: CommitResult | None = None,
) -> None:
    (session_dir / "commit_message.txt").write_text(
        render_commit_message(plan.message),
        encoding="utf-8",
    )
    (session_dir / "commit_plan.json").write_text(
        json.dumps(plan.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if result is not None:
        (session_dir / "commit_result.json").write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def run_git_commit(repo_root: Path, files: list[str], message_text: str) -> CommitResult:
    if not files:
        raise CommitError("Cannot commit: no files to stage.")

    add_result = _run_git(repo_root, ["add", "--", *files])

    if add_result.returncode != 0:
        return CommitResult(
            status="failed",
            files_staged=files,
            error=add_result.stderr.strip() or add_result.stdout.strip() or "git add failed",
            exit_code=add_result.returncode,
        )

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as message_file:
        message_file.write(message_text)
        message_path = Path(message_file.name)

    try:
        commit_result = _run_git(repo_root, ["commit", "-F", str(message_path)])
    finally:
        message_path.unlink(missing_ok=True)

    if commit_result.returncode != 0:
        return CommitResult(
            status="failed",
            files_staged=files,
            error=commit_result.stderr.strip() or commit_result.stdout.strip() or "git commit failed",
            exit_code=commit_result.returncode,
        )

    hash_result = _run_git(repo_root, ["rev-parse", "HEAD"])
    commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else None

    return CommitResult(
        status="committed",
        commit_hash=commit_hash,
        files_staged=files,
        message_subject=message_text.splitlines()[0] if message_text.splitlines() else None,
    )


def _normalize_patch_path(raw_path: str) -> str | None:
    stripped = raw_path.strip().strip('"')

    if stripped == "/dev/null":
        return None

    if stripped.startswith("a/") or stripped.startswith("b/"):
        stripped = stripped[2:]

    normalized = stripped.replace("\\", "/")
    pure_path = PurePosixPath(normalized)

    if not normalized or pure_path.is_absolute() or ".." in pure_path.parts:
        return None

    return str(pure_path)


def _parse_status_line(line: str) -> GitStatusEntry:
    index_status = line[0] if len(line) > 0 else " "
    worktree_status = line[1] if len(line) > 1 else " "
    path = line[3:] if len(line) > 3 else ""

    if " -> " in path:
        path = path.split(" -> ", 1)[1]

    return GitStatusEntry(
        path=path.strip().strip('"').replace("\\", "/"),
        index_status=index_status,
        worktree_status=worktree_status,
        raw=line,
    )


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None

    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _test_status(session_dir: Path) -> str | None:
    payload = _read_json(session_dir / "test_results.json")

    if isinstance(payload, dict) and isinstance(payload.get("status"), str):
        return payload["status"]

    return None


def _mode_specific_test_status(session_dir: Path, mode: str) -> str | None:
    file_name = (
        "sandbox_test_results.json"
        if mode == "sandbox"
        else "working_tree_test_results.json"
    )
    payload = _read_json(session_dir / file_name)

    if not isinstance(payload, dict):
        legacy = _read_json(session_dir / "test_results.json")

        if isinstance(legacy, dict) and legacy.get("mode", "working_tree") == mode:
            payload = legacy

    if isinstance(payload, dict) and isinstance(payload.get("status"), str):
        return payload["status"]

    return None


def _review_field(session_dir: Path, field_name: str) -> str | None:
    payload = _read_json(session_dir / "llm_review.json")

    if not isinstance(payload, dict):
        payload = _read_json(session_dir / "semantic_review.json")

    if isinstance(payload, dict) and isinstance(payload.get(field_name), str):
        return payload[field_name]

    return None


def _subject_from_change_summary(change_summary: str | None) -> str | None:
    if not change_summary:
        return None

    lines = change_summary.splitlines()

    for index, line in enumerate(lines):
        if line.strip() != "## Patch Summary":
            continue

        for summary_line in lines[index + 1 :]:
            stripped = summary_line.strip()

            if stripped.startswith("- "):
                return stripped[2:].rstrip(".")

            if stripped.startswith("## "):
                return None

    return None


def _subject_from_file_changes(file_changes: Any, files: list[str]) -> str:
    changes = file_changes.get("changes") if isinstance(file_changes, dict) else None

    if isinstance(changes, list) and changes:
        created_count = sum(
            1
            for change in changes
            if isinstance(change, dict) and change.get("change_type") == "created"
        )

        if created_count == len(changes):
            return "Add project files"

    if files and all(file.lower().endswith((".md", ".rst", ".txt")) for file in files):
        return "Update documentation"

    return "Update project files"


def _clean_subject(subject: str) -> str:
    cleaned = " ".join(subject.strip().split())

    if not cleaned:
        return "Update project files"

    return cleaned[:72].rstrip()


def _extract_json_object(text: str) -> Any:
    stripped_text = text.strip()
    decoder = json.JSONDecoder()

    for index, char in enumerate(stripped_text):
        if char != "{":
            continue

        try:
            parsed_value, _end_index = decoder.raw_decode(stripped_text[index:])
        except json.JSONDecodeError:
            continue

        return parsed_value

    raise ValueError("The commit message response does not contain a valid JSON object.")
