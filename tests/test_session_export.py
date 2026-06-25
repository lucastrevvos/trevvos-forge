"""Tests for session_export.py — SessionExporter and ExportResult."""
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from trevvos_forge.exceptions import SessionError
from trevvos_forge.session_export import ExportResult, SessionExporter


def _make_session(root: Path, session_id: str, files: dict[str, str | bytes] | None = None) -> Path:
    session_dir = root / ".trevvos" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    if files:
        for name, content in files.items():
            p = session_dir / name
            if isinstance(content, bytes):
                p.write_bytes(content)
            else:
                p.write_text(content, encoding="utf-8")
    return session_dir


class TestExportZip(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.session_id = "20240101-120000-abc123"
        _make_session(
            self.root,
            self.session_id,
            {
                "analysis.md": "# Analysis\nSome content here.\n",
                "metadata.json": json.dumps({"command": "analyze", "api_key": "secret123", "model": "llama3"}),
            },
        )
        self.exporter = SessionExporter(workspace_root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_export_zip_creates_file(self) -> None:
        out = self.root / "out.zip"
        result = self.exporter.export(self.session_id, format="zip", output_path=out)
        self.assertTrue(out.exists())
        self.assertEqual(result.format, "zip")
        self.assertEqual(result.session_id, self.session_id)
        self.assertIsInstance(result.duration_seconds, float)

    def test_export_zip_contains_manifest(self) -> None:
        out = self.root / "out.zip"
        self.exporter.export(self.session_id, format="zip", output_path=out)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        self.assertIn(f"trevvos-session-{self.session_id}/manifest.json", names)

    def test_export_zip_file_count(self) -> None:
        out = self.root / "out.zip"
        result = self.exporter.export(self.session_id, format="zip", output_path=out)
        self.assertEqual(result.file_count, 2)

    def test_export_zip_masks_json_secrets(self) -> None:
        out = self.root / "out.zip"
        self.exporter.export(self.session_id, format="zip", output_path=out)
        with zipfile.ZipFile(out) as zf:
            data = json.loads(zf.read(f"trevvos-session-{self.session_id}/session/metadata.json"))
        self.assertEqual(data["api_key"], "present")
        self.assertEqual(data["model"], "llama3")

    def test_export_zip_skips_large_files_by_default(self) -> None:
        session_dir = self.root / ".trevvos" / "sessions" / self.session_id
        large_content = b"x" * (2 * 1024 * 1024)
        (session_dir / "big.log").write_bytes(large_content)

        out = self.root / "out.zip"
        result = self.exporter.export(self.session_id, format="zip", output_path=out)

        self.assertEqual(result.skipped_large_files, 1)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        session_files = [n for n in names if "/session/" in n]
        self.assertFalse(any("big.log" in n for n in session_files))

    def test_export_zip_includes_large_when_flag_set(self) -> None:
        session_dir = self.root / ".trevvos" / "sessions" / self.session_id
        large_content = b"y" * (2 * 1024 * 1024)
        (session_dir / "big.log").write_bytes(large_content)

        out = self.root / "out.zip"
        result = self.exporter.export(
            self.session_id, format="zip", output_path=out, include_large_files=True
        )

        self.assertEqual(result.skipped_large_files, 0)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        self.assertTrue(any("big.log" in n for n in names))


class TestExportJson(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.session_id = "20240202-090000-def456"
        _make_session(
            self.root,
            self.session_id,
            {
                "summary.md": "## Summary\nContent.\n",
                "config.json": json.dumps({"provider": "ollama", "token": "mysecret", "model": "llama3"}),
            },
        )
        self.exporter = SessionExporter(workspace_root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_export_json_creates_file(self) -> None:
        out = self.root / "export.json"
        result = self.exporter.export(self.session_id, format="json", output_path=out)
        self.assertTrue(out.exists())
        self.assertEqual(result.format, "json")
        self.assertEqual(result.session_id, self.session_id)

    def test_export_json_structure(self) -> None:
        out = self.root / "export.json"
        self.exporter.export(self.session_id, format="json", output_path=out)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["export_version"], "1")
        self.assertEqual(data["session_id"], self.session_id)
        self.assertIn("manifest", data)
        self.assertIn("artifacts", data)
        self.assertIn("exported_at", data)

    def test_export_json_masks_secrets(self) -> None:
        out = self.root / "export.json"
        self.exporter.export(self.session_id, format="json", output_path=out)
        data = json.loads(out.read_text(encoding="utf-8"))
        artifacts = {a["name"]: a for a in data["artifacts"]}
        config_content = artifacts["config.json"]["content"]
        self.assertEqual(config_content["token"], "present")
        self.assertEqual(config_content["model"], "llama3")

    def test_export_json_artifact_has_content(self) -> None:
        out = self.root / "export.json"
        result = self.exporter.export(self.session_id, format="json", output_path=out)
        self.assertEqual(result.file_count, 2)
        data = json.loads(out.read_text(encoding="utf-8"))
        names = {a["name"] for a in data["artifacts"]}
        self.assertIn("summary.md", names)
        self.assertIn("config.json", names)


class TestSessionResolve(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.session_a = "20240101-080000-aaaa"
        self.session_b = "20240202-090000-bbbb"
        _make_session(self.root, self.session_a, {"note.txt": "a"})
        _make_session(self.root, self.session_b, {"note.txt": "b"})
        trevvos = self.root / ".trevvos"
        (trevvos / "current_session").write_text(self.session_a, encoding="utf-8")
        self.exporter = SessionExporter(workspace_root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_resolve_explicit_id(self) -> None:
        out = self.root / "out.zip"
        result = self.exporter.export(self.session_a, format="zip", output_path=out)
        self.assertEqual(result.session_id, self.session_a)

    def test_resolve_latest(self) -> None:
        out = self.root / "out.zip"
        result = self.exporter.export("latest", format="zip", output_path=out)
        self.assertEqual(result.session_id, self.session_b)

    def test_resolve_current(self) -> None:
        out = self.root / "out.zip"
        result = self.exporter.export("current", format="zip", output_path=out)
        self.assertEqual(result.session_id, self.session_a)

    def test_invalid_session_raises_error(self) -> None:
        with self.assertRaises(SessionError):
            self.exporter.export("nonexistent-session-id", format="zip")


if __name__ == "__main__":
    unittest.main()
