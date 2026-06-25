"""LocalApiService — read .trevvos/ and expose sessions/artifacts/config."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = frozenset({"api_key", "token", "secret", "password", "authorization", "auth"})

_METADATA_FILES = [
    "analysis_metadata.json",
    "explanation_metadata.json",
    "proposal_metadata.json",
    "handoff_metadata.json",
    "diff_review_metadata.json",
    "test_generation_metadata.json",
    "tests_inspect_metadata.json",
    "test_apply_result.json",
    "work_metadata.json",
    "plan_retry_metadata.json",
    "prompt_metadata.json",
]

_ARTIFACT_KINDS = {
    ".md": "markdown",
    ".json": "json",
    ".patch": "patch",
    ".diff": "patch",
    ".txt": "text",
    ".log": "log",
}

_MAX_ARTIFACT_BYTES = 1 * 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LocalApiError(Exception):
    pass


class SessionNotFoundError(LocalApiError):
    pass


class ArtifactNotFoundError(LocalApiError):
    pass


class ArtifactAccessError(LocalApiError):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_secrets(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: "present" if k.lower() in _SENSITIVE_KEYS else _mask_secrets(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_mask_secrets(item) for item in data]
    return data


def _artifact_kind(name: str) -> str:
    return _ARTIFACT_KINDS.get(Path(name).suffix.lower(), "unknown")


def _safe_read_json(path: Path) -> dict | list | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class LocalApiService:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self._trevvos = self.workspace_root / ".trevvos"

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def health(self) -> dict:
        return {
            "status": "ok",
            "service": "trevvos-forge-local-api",
            "workspace": str(self.workspace_root),
        }

    def project_profile(self) -> dict:
        profile_file = self._trevvos / "project_profile.json"
        if not profile_file.exists():
            return {
                "status": "missing",
                "message": "project_profile.json not found. Run `trevvos inspect` first.",
            }
        data = _safe_read_json(profile_file)
        if data is None:
            return {"status": "error", "message": "Failed to read project_profile.json."}
        return data  # type: ignore[return-value]

    def config(self) -> dict:
        config_file = self._trevvos / "config.json"
        if not config_file.exists():
            return {"status": "missing", "message": "config.json not found."}
        data = _safe_read_json(config_file)
        if data is None:
            return {"status": "error", "message": "Failed to read config.json."}
        return _mask_secrets(data)  # type: ignore[return-value]

    def list_sessions(self) -> list[dict]:
        sessions_dir = self._trevvos / "sessions"
        if not sessions_dir.exists():
            return []
        result = []
        try:
            entries = sorted(
                (e for e in sessions_dir.iterdir() if e.is_dir()),
                key=lambda e: e.name,
                reverse=True,
            )
        except OSError:
            return []
        for session_dir in entries:
            result.append(self._summarize_session(session_dir))
        return result

    def get_session(self, session_id: str) -> dict:
        session_dir = self._resolve_session(session_id)
        meta_combined: dict[str, Any] = {}
        for fname in _METADATA_FILES:
            f = session_dir / fname
            if not f.exists():
                continue
            data = _safe_read_json(f)
            if isinstance(data, dict):
                meta_combined.update(data)

        timeline: list = []
        tl_file = session_dir / "timeline.json"
        if tl_file.exists():
            tl = _safe_read_json(tl_file)
            if isinstance(tl, list):
                timeline = tl

        return {
            "id": session_id,
            "metadata": _mask_secrets(meta_combined),
            "timeline": timeline,
            "artifacts": self.list_artifacts(session_id),
        }

    def list_artifacts(self, session_id: str) -> list[dict]:
        session_dir = self._resolve_session(session_id)
        artifacts = []
        try:
            files = sorted(f for f in session_dir.iterdir() if f.is_file())
        except OSError:
            return []
        for f in files:
            try:
                stat = f.stat()
            except OSError:
                continue
            artifacts.append({
                "name": f.name,
                "kind": _artifact_kind(f.name),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "url": f"/sessions/{session_id}/artifacts/{f.name}",
            })
        return artifacts

    def get_artifact(self, session_id: str, artifact_name: str) -> dict:
        if ".." in artifact_name or "/" in artifact_name or "\\" in artifact_name:
            raise ArtifactAccessError(f"Invalid artifact name: {artifact_name!r}")

        session_dir = self._resolve_session(session_id)
        artifact_path = (session_dir / artifact_name).resolve()

        try:
            artifact_path.relative_to(session_dir.resolve())
        except ValueError:
            raise ArtifactAccessError(f"Path traversal detected: {artifact_name!r}")

        if not artifact_path.exists() or not artifact_path.is_file():
            raise ArtifactNotFoundError(
                f"Artifact {artifact_name!r} not found in session {session_id!r}."
            )

        kind = _artifact_kind(artifact_name)
        size = artifact_path.stat().st_size
        truncated = False

        if kind == "json":
            data = _safe_read_json(artifact_path)
            content: Any = _mask_secrets(data) if data is not None else None
        elif size > _MAX_ARTIFACT_BYTES:
            raw = artifact_path.read_bytes()[:_MAX_ARTIFACT_BYTES]
            content = raw.decode("utf-8", errors="replace")
            truncated = True
        else:
            content = artifact_path.read_text(encoding="utf-8", errors="replace")

        return {
            "name": artifact_name,
            "kind": kind,
            "content": content,
            "truncated": truncated,
            "size_bytes": size,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_session(self, session_id: str) -> Path:
        if ".." in session_id or "/" in session_id or "\\" in session_id:
            raise SessionNotFoundError(f"Invalid session id: {session_id!r}")
        sessions_dir = self._trevvos / "sessions"
        session_dir = sessions_dir / session_id
        if not session_dir.is_dir():
            raise SessionNotFoundError(f"Session {session_id!r} not found.")
        return session_dir

    def _summarize_session(self, session_dir: Path) -> dict:
        session_id = session_dir.name
        try:
            artifacts_count = sum(1 for f in session_dir.iterdir() if f.is_file())
        except OSError:
            artifacts_count = 0
        summary: dict[str, Any] = {
            "id": session_id,
            "path": session_dir.relative_to(self.workspace_root).as_posix(),
            "artifacts_count": artifacts_count,
        }
        for fname in _METADATA_FILES:
            f = session_dir / fname
            if not f.exists():
                continue
            data = _safe_read_json(f)
            if not isinstance(data, dict):
                continue
            for key in ("command", "mode", "status", "provider", "model", "duration_seconds", "created_at"):
                if key in data and key not in summary:
                    summary[key] = data[key]
            break
        return summary
