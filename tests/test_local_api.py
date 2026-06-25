"""Tests for Forge Local API — service layer and HTTP integration."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

import requests as http_requests

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.local_api.app import create_server
from trevvos_forge.local_api.service import (
    ArtifactAccessError,
    ArtifactNotFoundError,
    LocalApiService,
    SessionNotFoundError,
    _mask_secrets,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_workspace(tmp: str) -> Path:
    root = Path(tmp)
    trevvos = root / ".trevvos"
    trevvos.mkdir(parents=True)
    return root


def _make_session(workspace: Path, session_id: str, metadata: dict | None = None) -> Path:
    session_dir = workspace / ".trevvos" / "sessions" / session_id
    session_dir.mkdir(parents=True)
    if metadata:
        (session_dir / "analysis_metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
    return session_dir


# ---------------------------------------------------------------------------
# _mask_secrets unit tests
# ---------------------------------------------------------------------------

class TestMaskSecrets(unittest.TestCase):
    def test_masks_api_key(self) -> None:
        self.assertEqual(_mask_secrets({"api_key": "sk-secret"}), {"api_key": "present"})

    def test_masks_token(self) -> None:
        self.assertEqual(_mask_secrets({"token": "abc"}), {"token": "present"})

    def test_case_insensitive(self) -> None:
        self.assertEqual(_mask_secrets({"API_KEY": "x"}), {"API_KEY": "present"})

    def test_nested_masking(self) -> None:
        data = {"nested": {"secret": "val", "name": "forge"}}
        result = _mask_secrets(data)
        self.assertEqual(result["nested"]["secret"], "present")
        self.assertEqual(result["nested"]["name"], "forge")

    def test_list_masking(self) -> None:
        data = [{"token": "abc"}, {"name": "ok"}]
        result = _mask_secrets(data)
        self.assertEqual(result[0]["token"], "present")
        self.assertEqual(result[1]["name"], "ok")

    def test_non_sensitive_keys_unchanged(self) -> None:
        data = {"language": "pt-BR", "model": "qwen"}
        self.assertEqual(_mask_secrets(data), data)


# ---------------------------------------------------------------------------
# LocalApiService — health
# ---------------------------------------------------------------------------

class TestServiceHealth(unittest.TestCase):
    def test_health_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = LocalApiService(_make_workspace(tmp))
            result = svc.health()
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["service"], "trevvos-forge-local-api")
            self.assertIn("workspace", result)


# ---------------------------------------------------------------------------
# LocalApiService — project_profile
# ---------------------------------------------------------------------------

class TestServiceProjectProfile(unittest.TestCase):
    def test_missing_profile_returns_missing_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = LocalApiService(_make_workspace(tmp))
            result = svc.project_profile()
            self.assertEqual(result["status"], "missing")

    def test_existing_profile_returns_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            profile = {"files": ["calculator.py"], "language": "python"}
            (workspace / ".trevvos" / "project_profile.json").write_text(
                json.dumps(profile), encoding="utf-8"
            )
            svc = LocalApiService(workspace)
            result = svc.project_profile()
            self.assertEqual(result["files"], ["calculator.py"])


# ---------------------------------------------------------------------------
# LocalApiService — config
# ---------------------------------------------------------------------------

class TestServiceConfig(unittest.TestCase):
    def test_missing_config_returns_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = LocalApiService(_make_workspace(tmp))
            result = svc.config()
            self.assertEqual(result["status"], "missing")

    def test_config_masks_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            (workspace / ".trevvos" / "config.json").write_text(
                json.dumps({"language": "pt-BR", "api_key": "sk-secret"}), encoding="utf-8"
            )
            svc = LocalApiService(workspace)
            result = svc.config()
            self.assertEqual(result["api_key"], "present")
            self.assertEqual(result["language"], "pt-BR")
            self.assertNotIn("sk-secret", json.dumps(result))

    def test_config_masks_nested_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            config = {"name": "forge", "nested": {"token": "abc123", "mode": "local"}}
            (workspace / ".trevvos" / "config.json").write_text(
                json.dumps(config), encoding="utf-8"
            )
            svc = LocalApiService(workspace)
            result = svc.config()
            self.assertEqual(result["nested"]["token"], "present")
            self.assertEqual(result["nested"]["mode"], "local")
            self.assertNotIn("abc123", json.dumps(result))


# ---------------------------------------------------------------------------
# LocalApiService — list_sessions
# ---------------------------------------------------------------------------

class TestServiceListSessions(unittest.TestCase):
    def test_no_sessions_dir_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = LocalApiService(_make_workspace(tmp))
            self.assertEqual(svc.list_sessions(), [])

    def test_lists_sessions_sorted_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260620-120000-aaa111")
            _make_session(workspace, "20260623-183546-bbb222")
            svc = LocalApiService(workspace)
            sessions = svc.list_sessions()
            self.assertEqual(len(sessions), 2)
            self.assertEqual(sessions[0]["id"], "20260623-183546-bbb222")
            self.assertEqual(sessions[1]["id"], "20260620-120000-aaa111")

    def test_artifacts_count_is_correct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            session_dir = _make_session(workspace, "20260623-183546-abc001", {"command": "analyze"})
            (session_dir / "analysis_report.md").write_text("# Report", encoding="utf-8")
            svc = LocalApiService(workspace)
            sessions = svc.list_sessions()
            # 1 metadata file (analysis_metadata.json) + 1 report = 2
            self.assertEqual(sessions[0]["artifacts_count"], 2)

    def test_session_summary_includes_metadata_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260623-100000-abc", {
                "command": "analyze",
                "provider": "ollama",
                "model": "qwen2.5-coder:7b",
                "duration_seconds": 1.5,
            })
            svc = LocalApiService(workspace)
            sessions = svc.list_sessions()
            s = sessions[0]
            self.assertEqual(s["command"], "analyze")
            self.assertEqual(s["provider"], "ollama")
            self.assertEqual(s["model"], "qwen2.5-coder:7b")


# ---------------------------------------------------------------------------
# LocalApiService — get_session
# ---------------------------------------------------------------------------

class TestServiceGetSession(unittest.TestCase):
    def test_get_session_returns_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260623-183546-xyz", {"command": "analyze", "provider": "ollama"})
            svc = LocalApiService(workspace)
            result = svc.get_session("20260623-183546-xyz")
            self.assertEqual(result["id"], "20260623-183546-xyz")
            self.assertIn("metadata", result)
            self.assertIn("timeline", result)
            self.assertIn("artifacts", result)

    def test_get_session_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = LocalApiService(_make_workspace(tmp))
            with self.assertRaises(SessionNotFoundError):
                svc.get_session("does-not-exist")

    def test_get_session_loads_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            session_dir = _make_session(workspace, "20260623-180000-tl")
            timeline_data = [{"event": "started", "ts": "2026-06-23T18:00:00"}]
            (session_dir / "timeline.json").write_text(json.dumps(timeline_data), encoding="utf-8")
            svc = LocalApiService(workspace)
            result = svc.get_session("20260623-180000-tl")
            self.assertEqual(result["timeline"], timeline_data)

    def test_get_session_metadata_secrets_masked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260623-180000-sec", {"api_key": "sk-hidden", "command": "analyze"})
            svc = LocalApiService(workspace)
            result = svc.get_session("20260623-180000-sec")
            self.assertEqual(result["metadata"]["api_key"], "present")
            self.assertNotIn("sk-hidden", json.dumps(result))


# ---------------------------------------------------------------------------
# LocalApiService — list_artifacts
# ---------------------------------------------------------------------------

class TestServiceListArtifacts(unittest.TestCase):
    def test_list_artifacts_classifies_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            session_dir = _make_session(workspace, "20260623-183546-art")
            (session_dir / "report.md").write_text("# Report", encoding="utf-8")
            (session_dir / "meta.json").write_text("{}", encoding="utf-8")
            (session_dir / "changes.patch").write_text("--- a\n+++ b", encoding="utf-8")
            (session_dir / "log.log").write_text("log", encoding="utf-8")
            (session_dir / "data.xyz").write_text("?", encoding="utf-8")
            svc = LocalApiService(workspace)
            artifacts = svc.list_artifacts("20260623-183546-art")
            kinds = {a["name"]: a["kind"] for a in artifacts}
            self.assertEqual(kinds["report.md"], "markdown")
            self.assertEqual(kinds["meta.json"], "json")
            self.assertEqual(kinds["changes.patch"], "patch")
            self.assertEqual(kinds["log.log"], "log")
            self.assertEqual(kinds["data.xyz"], "unknown")

    def test_list_artifacts_includes_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            session_dir = _make_session(workspace, "20260623-183546-url")
            (session_dir / "report.md").write_text("x", encoding="utf-8")
            svc = LocalApiService(workspace)
            artifacts = svc.list_artifacts("20260623-183546-url")
            self.assertIn("/sessions/20260623-183546-url/artifacts/report.md", artifacts[0]["url"])

    def test_list_artifacts_unknown_session_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = LocalApiService(_make_workspace(tmp))
            with self.assertRaises(SessionNotFoundError):
                svc.list_artifacts("nope")


# ---------------------------------------------------------------------------
# LocalApiService — get_artifact
# ---------------------------------------------------------------------------

class TestServiceGetArtifact(unittest.TestCase):
    def test_get_markdown_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            session_dir = _make_session(workspace, "20260623-183546-md")
            (session_dir / "report.md").write_text("# Hello", encoding="utf-8")
            svc = LocalApiService(workspace)
            result = svc.get_artifact("20260623-183546-md", "report.md")
            self.assertEqual(result["kind"], "markdown")
            self.assertEqual(result["content"], "# Hello")
            self.assertFalse(result["truncated"])

    def test_get_json_artifact_masks_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            session_dir = _make_session(workspace, "20260623-183546-js")
            (session_dir / "meta.json").write_text(
                json.dumps({"api_key": "sk-secret", "command": "analyze"}), encoding="utf-8"
            )
            svc = LocalApiService(workspace)
            result = svc.get_artifact("20260623-183546-js", "meta.json")
            self.assertEqual(result["content"]["api_key"], "present")
            self.assertNotIn("sk-secret", json.dumps(result))

    def test_path_traversal_dotdot_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260623-183546-pt")
            svc = LocalApiService(workspace)
            with self.assertRaises(ArtifactAccessError):
                svc.get_artifact("20260623-183546-pt", "../config.json")

    def test_path_traversal_backslash_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260623-183546-pt2")
            svc = LocalApiService(workspace)
            with self.assertRaises(ArtifactAccessError):
                svc.get_artifact("20260623-183546-pt2", "..\\config.json")

    def test_path_traversal_slash_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260623-183546-pt3")
            svc = LocalApiService(workspace)
            with self.assertRaises(ArtifactAccessError):
                svc.get_artifact("20260623-183546-pt3", "subdir/file.json")

    def test_missing_artifact_raises_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260623-183546-nf")
            svc = LocalApiService(workspace)
            with self.assertRaises(ArtifactNotFoundError):
                svc.get_artifact("20260623-183546-nf", "does_not_exist.md")

    def test_unknown_session_raises_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = LocalApiService(_make_workspace(tmp))
            with self.assertRaises(SessionNotFoundError):
                svc.get_artifact("nope", "file.md")


# ---------------------------------------------------------------------------
# HTTP integration tests
# ---------------------------------------------------------------------------

class TestHttpIntegration(unittest.TestCase):
    """Spin up a real server on port=0 and test via requests."""

    def _start(self, workspace: Path) -> tuple:
        server = create_server(workspace_root=workspace, host="127.0.0.1", port=0)
        host, port = server.server_address
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server, host, port

    def _stop(self, server: object) -> None:
        server.shutdown()  # type: ignore[union-attr]
        server.server_close()  # type: ignore[union-attr]

    def test_http_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            server, host, port = self._start(workspace)
            try:
                resp = http_requests.get(f"http://{host}:{port}/health", timeout=5)
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["status"], "ok")
            finally:
                self._stop(server)

    def test_http_sessions_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            server, host, port = self._start(workspace)
            try:
                resp = http_requests.get(f"http://{host}:{port}/sessions", timeout=5)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json(), [])
            finally:
                self._stop(server)

    def test_http_sessions_with_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260623-183546-h01", {"command": "analyze"})
            server, host, port = self._start(workspace)
            try:
                resp = http_requests.get(f"http://{host}:{port}/sessions", timeout=5)
                data = resp.json()
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["id"], "20260623-183546-h01")
            finally:
                self._stop(server)

    def test_http_session_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            server, host, port = self._start(workspace)
            try:
                resp = http_requests.get(f"http://{host}:{port}/sessions/nope", timeout=5)
                self.assertEqual(resp.status_code, 404)
            finally:
                self._stop(server)

    def test_http_path_traversal_returns_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            _make_session(workspace, "20260623-183546-tr")
            server, host, port = self._start(workspace)
            try:
                resp = http_requests.get(
                    f"http://{host}:{port}/sessions/20260623-183546-tr/artifacts/../config.json",
                    timeout=5,
                )
                # Traversal in URL is normalized by http.server; artifact name check still blocks
                self.assertIn(resp.status_code, (400, 404))
            finally:
                self._stop(server)

    def test_http_unknown_route_returns_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = _make_workspace(tmp)
            server, host, port = self._start(workspace)
            try:
                resp = http_requests.get(f"http://{host}:{port}/unknown/route", timeout=5)
                self.assertEqual(resp.status_code, 404)
            finally:
                self._stop(server)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestApiCLI(unittest.TestCase):
    def test_api_start_help(self) -> None:
        result = runner.invoke(app, ["api", "start", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--host", result.output)
        self.assertIn("--port", result.output)
        self.assertIn("--path", result.output)

    def test_api_help(self) -> None:
        result = runner.invoke(app, ["api", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("start", result.output)


if __name__ == "__main__":
    unittest.main()
