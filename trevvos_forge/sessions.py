import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from trevvos_forge.exceptions import SessionError


TREVVOS_DIR_NAME = ".trevvos"
SESSIONS_DIR_NAME = "sessions"
CURRENT_SESSION_FILE_NAME = "current_session"


@dataclass(frozen=True)
class SessionMetadata:
    id: str
    created_at: str
    status: str
    command: str
    workspace_root: str


@dataclass(frozen=True)
class ForgeSession:
    metadata: SessionMetadata
    path: Path


def create_session(root: Path, user_request: str, command: str = "manual") -> ForgeSession:
    workspace_root = _workspace_root(root)

    session_id = _generate_session_id()
    session_path = _sessions_dir(workspace_root) / session_id

    if session_path.exists():
        raise SessionError(f"Session already exists: {session_id}")

    session_path.mkdir(parents=True)

    metadata = SessionMetadata(
        id=session_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        status="created",
        command=command,
        workspace_root=str(workspace_root),
    )

    _write_json(session_path / "metadata.json", asdict(metadata))
    _write_text(session_path / "user_request.txt", user_request)
    _set_current_session_id(workspace_root, session_id)

    return ForgeSession(
        metadata=metadata,
        path=session_path,
    )


def get_current_session_id(root: Path) -> str:
    workspace_root = _workspace_root(root)
    current_file = _current_session_file(workspace_root)

    if not current_file.exists():
        raise SessionError("No current session found.")

    session_id = current_file.read_text(encoding="utf-8").strip()

    if not session_id:
        raise SessionError("Current session file is empty.")

    return session_id


def get_current_session(root: Path) -> ForgeSession:
    session_id = get_current_session_id(root)

    return get_session(root=root, session_id=session_id)


def get_session(root: Path, session_id: str) -> ForgeSession:
    workspace_root = _workspace_root(root)
    session_path = _sessions_dir(workspace_root) / session_id

    if not session_path.exists():
        raise SessionError(f"Session not found: {session_id}")

    if not session_path.is_dir():
        raise SessionError(f"Session path exists but is not a directory: {session_path}")

    metadata_path = session_path / "metadata.json"

    if not metadata_path.exists():
        raise SessionError(f"Session metadata not found: {session_id}")

    try:
        raw_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SessionError(f"Session metadata is invalid JSON: {session_id}") from exc

    metadata = SessionMetadata(
        id=str(raw_metadata["id"]),
        created_at=str(raw_metadata["created_at"]),
        status=str(raw_metadata["status"]),
        command=str(raw_metadata["command"]),
        workspace_root=str(raw_metadata["workspace_root"]),
    )

    return ForgeSession(
        metadata=metadata,
        path=session_path,
    )


def list_sessions(root: Path) -> list[ForgeSession]:
    workspace_root = _workspace_root(root)
    sessions_dir = _sessions_dir(workspace_root)

    if not sessions_dir.exists():
        return []

    if not sessions_dir.is_dir():
        raise SessionError(f"Sessions path exists but is not a directory: {sessions_dir}")

    sessions: list[ForgeSession] = []

    for session_path in sorted(sessions_dir.iterdir(), reverse=True):
        if not session_path.is_dir():
            continue

        try:
            sessions.append(get_session(root=workspace_root, session_id=session_path.name))
        except SessionError:
            continue

    return sessions


def read_session_text(session: ForgeSession, file_name: str) -> str:
    file_path = session.path / file_name

    if not file_path.exists():
        raise SessionError(f"Session file not found: {file_name}")

    return file_path.read_text(encoding="utf-8")


def write_session_text(session: ForgeSession, file_name: str, content: str) -> None:
    _write_text(session.path / file_name, content)


def clean_sessions(root: Path) -> None:
    workspace_root = _workspace_root(root)
    trevvos_dir = _trevvos_dir(workspace_root)

    if trevvos_dir.exists():
        shutil.rmtree(trevvos_dir)


def _workspace_root(root: Path) -> Path:
    workspace_root = root.resolve()

    if not workspace_root.exists():
        raise SessionError(f"Workspace path does not exist: {workspace_root}")

    if not workspace_root.is_dir():
        raise SessionError(f"Workspace path is not a directory: {workspace_root}")

    return workspace_root


def _generate_session_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]

    return f"{timestamp}-{suffix}"


def _trevvos_dir(root: Path) -> Path:
    return root / TREVVOS_DIR_NAME


def _sessions_dir(root: Path) -> Path:
    return _trevvos_dir(root) / SESSIONS_DIR_NAME


def _current_session_file(root: Path) -> Path:
    return _trevvos_dir(root) / CURRENT_SESSION_FILE_NAME


def _set_current_session_id(root: Path, session_id: str) -> None:
    trevvos_dir = _trevvos_dir(root)
    trevvos_dir.mkdir(parents=True, exist_ok=True)

    _write_text(_current_session_file(root), session_id)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
