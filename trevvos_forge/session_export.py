"""Session export — portable ZIP or JSON exports with secret masking."""
from __future__ import annotations

import json
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trevvos_forge.exceptions import SessionError
from trevvos_forge.redaction import mask_secrets

EXPORT_VERSION = "1"
_DEFAULT_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB

_ARTIFACT_KINDS = {
    ".md": "markdown",
    ".json": "json",
    ".patch": "patch",
    ".diff": "patch",
    ".txt": "text",
    ".log": "log",
}


def _artifact_kind(name: str) -> str:
    return _ARTIFACT_KINDS.get(Path(name).suffix.lower(), "unknown")


@dataclass
class ExportResult:
    session_id: str
    format: str
    output_path: Path
    file_count: int
    total_bytes: int
    skipped_symlinks: int
    skipped_large_files: int
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "format": self.format,
            "output_path": str(self.output_path),
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "skipped_symlinks": self.skipped_symlinks,
            "skipped_large_files": self.skipped_large_files,
            "duration_seconds": self.duration_seconds,
        }


class SessionExporter:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self._trevvos = self.workspace_root / ".trevvos"
        self._sessions_dir = self._trevvos / "sessions"

    def export(
        self,
        session_ref: str,
        *,
        format: str = "zip",
        output_path: Path | None = None,
        include_large_files: bool = False,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
    ) -> ExportResult:
        if format not in ("zip", "json"):
            raise ValueError(f"Unsupported export format: {format!r}. Use 'zip' or 'json'.")

        t0 = time.perf_counter()
        session_id = self._resolve_session_id(session_ref)
        session_dir = self._sessions_dir / session_id

        if output_path is None:
            ext = ".zip" if format == "zip" else ".json"
            output_path = Path(f"trevvos-session-{session_id}{ext}")

        exported_at = datetime.now(timezone.utc).isoformat()

        if format == "zip":
            counts = self._export_zip(
                session_id=session_id,
                session_dir=session_dir,
                output_path=output_path,
                include_large_files=include_large_files,
                max_file_bytes=max_file_bytes,
                exported_at=exported_at,
            )
        else:
            counts = self._export_json(
                session_id=session_id,
                session_dir=session_dir,
                output_path=output_path,
                include_large_files=include_large_files,
                max_file_bytes=max_file_bytes,
                exported_at=exported_at,
            )

        return ExportResult(
            session_id=session_id,
            format=format,
            output_path=output_path.resolve(),
            file_count=counts["file_count"],
            total_bytes=counts["total_bytes"],
            skipped_symlinks=counts["skipped_symlinks"],
            skipped_large_files=counts["skipped_large_files"],
            duration_seconds=round(time.perf_counter() - t0, 2),
        )

    def _resolve_session_id(self, session_ref: str) -> str:
        if session_ref == "current":
            current_file = self._trevvos / "current_session"
            if not current_file.exists():
                raise SessionError("No current session found.")
            session_id = current_file.read_text(encoding="utf-8").strip()
            if not session_id:
                raise SessionError("Current session file is empty.")
        elif session_ref == "latest":
            if not self._sessions_dir.exists():
                raise SessionError("No sessions found.")
            dirs = sorted(
                (d for d in self._sessions_dir.iterdir() if d.is_dir()),
                key=lambda d: d.name,
            )
            if not dirs:
                raise SessionError("No sessions found.")
            session_id = dirs[-1].name
        else:
            session_id = session_ref

        if ".." in session_id or "/" in session_id or "\\" in session_id:
            raise SessionError(f"Invalid session id: {session_id!r}")

        session_dir = self._sessions_dir / session_id
        if not session_dir.is_dir():
            raise SessionError(f"Session not found: {session_id!r}")

        return session_id

    def _collect_files(
        self,
        session_dir: Path,
        include_large_files: bool,
        max_file_bytes: int,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Return (file_records, skipped_symlinks, skipped_large_files)."""
        records: list[dict[str, Any]] = []
        skipped_symlinks = 0
        skipped_large_files = 0

        try:
            raw_entries = sorted(f for f in session_dir.iterdir() if not f.is_dir())
        except OSError as exc:
            raise SessionError(f"Cannot read session directory: {exc}") from exc

        resolved_session = session_dir.resolve()

        for f in raw_entries:
            try:
                f.resolve().relative_to(resolved_session)
            except ValueError:
                continue

            if f.is_symlink():
                records.append({
                    "name": f.name,
                    "kind": _artifact_kind(f.name),
                    "size_bytes": 0,
                    "skipped": True,
                    "reason": "symlink",
                })
                skipped_symlinks += 1
                continue

            try:
                size = f.stat().st_size
            except OSError:
                continue

            if not include_large_files and size > max_file_bytes:
                records.append({
                    "name": f.name,
                    "kind": _artifact_kind(f.name),
                    "size_bytes": size,
                    "skipped": True,
                    "reason": "large",
                })
                skipped_large_files += 1
                continue

            records.append({
                "name": f.name,
                "kind": _artifact_kind(f.name),
                "size_bytes": size,
                "skipped": False,
            })

        return records, skipped_symlinks, skipped_large_files

    def _export_zip(
        self,
        *,
        session_id: str,
        session_dir: Path,
        output_path: Path,
        include_large_files: bool,
        max_file_bytes: int,
        exported_at: str,
    ) -> dict[str, int]:
        records, skipped_symlinks, skipped_large_files = self._collect_files(
            session_dir, include_large_files, max_file_bytes
        )

        prefix = f"trevvos-session-{session_id}"
        file_count = 0
        total_bytes = 0

        manifest = {
            "export_version": EXPORT_VERSION,
            "session_id": session_id,
            "exported_at": exported_at,
            "files": records,
        }

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                f"{prefix}/manifest.json",
                json.dumps(manifest, indent=2, default=str),
            )
            for rec in records:
                if rec["skipped"]:
                    continue
                artifact_path = session_dir / rec["name"]
                try:
                    if rec["kind"] == "json":
                        try:
                            data = json.loads(artifact_path.read_text(encoding="utf-8"))
                            data_bytes = json.dumps(
                                mask_secrets(data), indent=2, default=str
                            ).encode("utf-8")
                        except (ValueError, OSError):
                            data_bytes = artifact_path.read_bytes()
                    else:
                        data_bytes = artifact_path.read_bytes()
                except OSError:
                    continue
                zf.writestr(f"{prefix}/session/{rec['name']}", data_bytes)
                file_count += 1
                total_bytes += len(data_bytes)

        return {
            "file_count": file_count,
            "total_bytes": total_bytes,
            "skipped_symlinks": skipped_symlinks,
            "skipped_large_files": skipped_large_files,
        }

    def _export_json(
        self,
        *,
        session_id: str,
        session_dir: Path,
        output_path: Path,
        include_large_files: bool,
        max_file_bytes: int,
        exported_at: str,
    ) -> dict[str, int]:
        records, skipped_symlinks, skipped_large_files = self._collect_files(
            session_dir, include_large_files, max_file_bytes
        )

        artifacts: list[dict[str, Any]] = []
        file_count = 0
        total_bytes = 0

        for rec in records:
            if rec["skipped"]:
                continue
            artifact_path = session_dir / rec["name"]
            kind = rec["kind"]
            size = rec["size_bytes"]
            truncated = False
            content: Any = None

            try:
                if kind == "json":
                    try:
                        raw_data = json.loads(artifact_path.read_text(encoding="utf-8"))
                        content = mask_secrets(raw_data)
                    except (ValueError, OSError):
                        content = None
                else:
                    raw_bytes = artifact_path.read_bytes()
                    if not include_large_files and len(raw_bytes) > max_file_bytes:
                        raw_bytes = raw_bytes[:max_file_bytes]
                        truncated = True
                    content = raw_bytes.decode("utf-8", errors="replace")
            except OSError:
                continue

            artifacts.append({
                "name": rec["name"],
                "kind": kind,
                "content": content,
                "truncated": truncated,
                "size_bytes": size,
            })
            file_count += 1
            total_bytes += size

        manifest = {
            "export_version": EXPORT_VERSION,
            "session_id": session_id,
            "exported_at": exported_at,
            "files": records,
        }

        export_data = {
            "export_version": EXPORT_VERSION,
            "session_id": session_id,
            "exported_at": exported_at,
            "manifest": manifest,
            "artifacts": artifacts,
        }

        output_path.write_text(
            json.dumps(export_data, indent=2, default=str), encoding="utf-8"
        )

        return {
            "file_count": file_count,
            "total_bytes": total_bytes,
            "skipped_symlinks": skipped_symlinks,
            "skipped_large_files": skipped_large_files,
        }
