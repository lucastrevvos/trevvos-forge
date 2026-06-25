"""Tests for the Forge Dashboard — static asset serving and HTTP routing."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests as http_requests

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.local_api.app import create_server

runner = CliRunner()


def _make_workspace(tmp: str) -> Path:
    root = Path(tmp)
    (root / ".trevvos").mkdir(parents=True)
    return root


class _ServerFixture(unittest.TestCase):
    """Base class that spins up a real server on an OS-assigned port."""

    _server = None
    _host: str = ""
    _port: int = 0

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        workspace = _make_workspace(self._tmp.name)
        self._server = create_server(workspace_root=workspace, host="127.0.0.1", port=0)
        self._host, self._port = self._server.server_address
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()

    def tearDown(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._tmp.cleanup()

    def _url(self, path: str) -> str:
        return f"http://{self._host}:{self._port}{path}"

    def _get(self, path: str, **kwargs) -> http_requests.Response:
        return http_requests.get(self._url(path), timeout=5, **kwargs)


# ---------------------------------------------------------------------------
# Dashboard root  GET /
# ---------------------------------------------------------------------------

class TestDashboardRoot(_ServerFixture):
    def test_root_returns_200(self) -> None:
        resp = self._get("/")
        self.assertEqual(resp.status_code, 200)

    def test_root_content_type_html(self) -> None:
        resp = self._get("/")
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))

    def test_root_contains_title(self) -> None:
        resp = self._get("/")
        self.assertIn("Trevvos Forge Dashboard", resp.text)

    def test_html_references_css(self) -> None:
        resp = self._get("/")
        self.assertIn("/static/dashboard.css", resp.text)

    def test_html_references_js(self) -> None:
        resp = self._get("/")
        self.assertIn("/static/dashboard.js", resp.text)


# ---------------------------------------------------------------------------
# Static assets  GET /static/...
# ---------------------------------------------------------------------------

class TestStaticAssets(_ServerFixture):
    def test_css_returns_200(self) -> None:
        resp = self._get("/static/dashboard.css")
        self.assertEqual(resp.status_code, 200)

    def test_css_content_type(self) -> None:
        resp = self._get("/static/dashboard.css")
        self.assertIn("css", resp.headers.get("Content-Type", ""))

    def test_js_returns_200(self) -> None:
        resp = self._get("/static/dashboard.js")
        self.assertEqual(resp.status_code, 200)

    def test_js_contains_fetch_sessions(self) -> None:
        resp = self._get("/static/dashboard.js")
        self.assertIn("fetch", resp.text)
        self.assertIn("/sessions", resp.text)

    def test_missing_asset_returns_404(self) -> None:
        resp = self._get("/static/missing.js")
        self.assertEqual(resp.status_code, 404)

    def test_path_traversal_static_returns_404(self) -> None:
        resp = self._get("/static/../handler.py", allow_redirects=False)
        self.assertIn(resp.status_code, (400, 404))


# ---------------------------------------------------------------------------
# Existing API unbroken
# ---------------------------------------------------------------------------

class TestExistingApiUnbroken(_ServerFixture):
    def test_health_still_works(self) -> None:
        resp = self._get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_sessions_still_works(self) -> None:
        resp = self._get("/sessions")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_unknown_route_still_404(self) -> None:
        resp = self._get("/does-not-exist")
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# CLI output
# ---------------------------------------------------------------------------

class TestApiCliDashboard(unittest.TestCase):
    def test_help_contains_open_flag(self) -> None:
        result = runner.invoke(app, ["api", "start", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--open", result.output)

    def test_cli_output_contains_dashboard(self) -> None:
        with patch("trevvos_forge.local_api.app.run_server", side_effect=KeyboardInterrupt):
            result = runner.invoke(app, ["api", "start", "--port", "9999"])
        self.assertIn("Dashboard:", result.output)
        self.assertIn("http://127.0.0.1:9999/", result.output)

    def test_open_flag_calls_webbrowser(self) -> None:
        with patch("trevvos_forge.local_api.app.run_server", side_effect=KeyboardInterrupt):
            with patch("webbrowser.open") as mock_open:
                runner.invoke(app, ["api", "start", "--open", "--port", "9998"])
        mock_open.assert_called_once_with("http://127.0.0.1:9998/")


if __name__ == "__main__":
    unittest.main()
