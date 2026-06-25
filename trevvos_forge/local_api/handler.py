"""HTTP request handler for the Forge Local API."""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse

from trevvos_forge.local_api.service import (
    ArtifactAccessError,
    ArtifactNotFoundError,
    LocalApiService,
    SessionNotFoundError,
)

# Route patterns: (compiled_regex, handler_method_name, group_names)
_ROUTES = [
    (re.compile(r"^/health$"), "health", ()),
    (re.compile(r"^/project/profile$"), "project_profile", ()),
    (re.compile(r"^/config$"), "config", ()),
    (re.compile(r"^/sessions$"), "sessions", ()),
    (re.compile(r"^/sessions/([^/]+)/artifacts/(.+)$"), "session_artifact", ("session_id", "artifact_name")),
    (re.compile(r"^/sessions/([^/]+)/artifacts$"), "session_artifacts", ("session_id",)),
    (re.compile(r"^/sessions/([^/]+)$"), "session", ("session_id",)),
]


class ForgeApiHandler(BaseHTTPRequestHandler):
    service: LocalApiService

    def log_message(self, format: str, *args: Any) -> None:
        pass  # suppress default stdout logging

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        for pattern, handler_name, group_names in _ROUTES:
            m = pattern.match(path)
            if m is None:
                continue
            groups = dict(zip(group_names, m.groups()))
            try:
                self._dispatch(handler_name, groups)
            except SessionNotFoundError as exc:
                self._send_json({"error": str(exc)}, 404)
            except ArtifactNotFoundError as exc:
                self._send_json({"error": str(exc)}, 404)
            except ArtifactAccessError as exc:
                self._send_json({"error": str(exc)}, 400)
            except Exception as exc:
                self._send_json({"error": "Internal server error", "detail": str(exc)}, 500)
            return
        self._send_json({"error": "Not found", "path": path}, 404)

    def _dispatch(self, handler_name: str, groups: dict[str, str]) -> None:
        svc = self.service
        if handler_name == "health":
            self._send_json(svc.health())
        elif handler_name == "project_profile":
            self._send_json(svc.project_profile())
        elif handler_name == "config":
            self._send_json(svc.config())
        elif handler_name == "sessions":
            self._send_json(svc.list_sessions())
        elif handler_name == "session":
            self._send_json(svc.get_session(groups["session_id"]))
        elif handler_name == "session_artifacts":
            self._send_json(svc.list_artifacts(groups["session_id"]))
        elif handler_name == "session_artifact":
            self._send_json(svc.get_artifact(groups["session_id"], groups["artifact_name"]))
        else:
            self._send_json({"error": "Unknown handler"}, 500)
