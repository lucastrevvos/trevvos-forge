"""Tests for Marco 83 packaging infrastructure."""
from __future__ import annotations

import unittest
from pathlib import Path

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.version import __version__

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


# ---------------------------------------------------------------------------
# 1. Packaging files exist
# ---------------------------------------------------------------------------

class TestPackagingFilesExist(unittest.TestCase):
    def test_entry_point_exists(self) -> None:
        self.assertTrue((ROOT / "packaging" / "trevvos_entry.py").exists())

    def test_build_windows_exists(self) -> None:
        self.assertTrue((ROOT / "packaging" / "build_windows.ps1").exists())

    def test_build_linux_exists(self) -> None:
        self.assertTrue((ROOT / "packaging" / "build_linux.sh").exists())

    def test_build_release_exists(self) -> None:
        self.assertTrue((ROOT / "packaging" / "build_release.py").exists())

    def test_binary_readme_exists(self) -> None:
        self.assertTrue((ROOT / "packaging" / "README_BINARY_DISTRIBUTION.md").exists())

    def test_github_workflow_exists(self) -> None:
        self.assertTrue((ROOT / ".github" / "workflows" / "build-binaries.yml").exists())


# ---------------------------------------------------------------------------
# 2. Build scripts include dashboard assets
# ---------------------------------------------------------------------------

class TestBuildScriptsDashboardAssets(unittest.TestCase):
    def test_windows_script_includes_static(self) -> None:
        text = _read("packaging/build_windows.ps1")
        self.assertIn("local_api\\static", text)

    def test_linux_script_includes_static(self) -> None:
        text = _read("packaging/build_linux.sh")
        self.assertIn("local_api/static", text)


# ---------------------------------------------------------------------------
# 3. Build scripts include docs
# ---------------------------------------------------------------------------

class TestBuildScriptsDocs(unittest.TestCase):
    def test_windows_includes_readme(self) -> None:
        text = _read("packaging/build_windows.ps1")
        self.assertIn("README.md", text)

    def test_windows_includes_alpha_md(self) -> None:
        text = _read("packaging/build_windows.ps1")
        self.assertIn("ALPHA.md", text)

    def test_windows_includes_docs_dir(self) -> None:
        text = _read("packaging/build_windows.ps1")
        self.assertIn('"docs;docs"', text)

    def test_linux_includes_readme(self) -> None:
        text = _read("packaging/build_linux.sh")
        self.assertIn("README.md", text)

    def test_linux_includes_alpha_md(self) -> None:
        text = _read("packaging/build_linux.sh")
        self.assertIn("ALPHA.md", text)

    def test_linux_includes_docs_dir(self) -> None:
        text = _read("packaging/build_linux.sh")
        self.assertIn('"docs:docs"', text)


# ---------------------------------------------------------------------------
# 4. Build scripts use --onedir not --onefile
# ---------------------------------------------------------------------------

class TestBuildScriptsOnedir(unittest.TestCase):
    def test_windows_uses_onedir(self) -> None:
        text = _read("packaging/build_windows.ps1")
        self.assertIn("--onedir", text)
        self.assertNotIn("--onefile", text)

    def test_linux_uses_onedir(self) -> None:
        text = _read("packaging/build_linux.sh")
        self.assertIn("--onedir", text)
        self.assertNotIn("--onefile", text)


# ---------------------------------------------------------------------------
# 5. Build scripts do not include .trevvos
# ---------------------------------------------------------------------------

class TestBuildScriptsNoTrevvosData(unittest.TestCase):
    def test_windows_does_not_include_trevvos_dir(self) -> None:
        text = _read("packaging/build_windows.ps1").lower()
        self.assertNotIn("add-data \".trevvos", text)

    def test_linux_does_not_include_trevvos_dir(self) -> None:
        text = _read("packaging/build_linux.sh")
        self.assertNotIn('--add-data ".trevvos', text)


# ---------------------------------------------------------------------------
# 6. Workflow has Windows and Linux jobs
# ---------------------------------------------------------------------------

class TestWorkflowJobs(unittest.TestCase):
    def test_workflow_has_windows_job(self) -> None:
        text = _read(".github/workflows/build-binaries.yml")
        self.assertIn("windows-latest", text)

    def test_workflow_has_linux_job(self) -> None:
        text = _read(".github/workflows/build-binaries.yml")
        self.assertIn("ubuntu-22.04", text)

    def test_workflow_uploads_artifacts(self) -> None:
        text = _read(".github/workflows/build-binaries.yml")
        self.assertIn("actions/upload-artifact", text)

    def test_workflow_triggers_on_version_tag(self) -> None:
        text = _read(".github/workflows/build-binaries.yml")
        self.assertIn("v*", text)

    def test_workflow_has_workflow_dispatch(self) -> None:
        text = _read(".github/workflows/build-binaries.yml")
        self.assertIn("workflow_dispatch", text)


# ---------------------------------------------------------------------------
# 7. Binary docs mention no runtime/model bundled
# ---------------------------------------------------------------------------

class TestBinaryReadme(unittest.TestCase):
    def test_readme_mentions_no_runtime_bundled(self) -> None:
        text = _read("packaging/README_BINARY_DISTRIBUTION.md").lower()
        self.assertIn("not included", text)
        self.assertIn("ollama", text)
        self.assertIn("onedir", text)

    def test_readme_covers_windows_and_linux(self) -> None:
        text = _read("packaging/README_BINARY_DISTRIBUTION.md").lower()
        self.assertIn("windows", text)
        self.assertIn("linux", text)
        self.assertIn("sha256", text)


# ---------------------------------------------------------------------------
# 8. Alpha docs mention binary installation
# ---------------------------------------------------------------------------

class TestAlphaDocsBinaryInstall(unittest.TestCase):
    def test_alpha_md_mentions_binary_download(self) -> None:
        text = _read("ALPHA.md").lower()
        self.assertIn("windows-x64.zip", text)
        self.assertIn("linux-x64.tar.gz", text)

    def test_quickstart_mentions_binary_install(self) -> None:
        text = _read("docs/alpha-quickstart.md").lower()
        self.assertIn("no python", text)
        self.assertIn("windows-x64.zip", text)
        self.assertIn("linux-x64.tar.gz", text)


# ---------------------------------------------------------------------------
# 9. Version module and CLI command
# ---------------------------------------------------------------------------

class TestVersionModule(unittest.TestCase):
    def test_version_is_string(self) -> None:
        self.assertIsInstance(__version__, str)

    def test_version_not_empty(self) -> None:
        self.assertTrue(__version__)

    def test_version_matches_expected(self) -> None:
        self.assertEqual(__version__, "0.1.0-alpha.1")


class TestVersionCliCommand(unittest.TestCase):
    def test_version_command_exits_zero(self) -> None:
        result = runner.invoke(app, ["version"])
        self.assertEqual(result.exit_code, 0, result.output)

    def test_version_command_prints_version(self) -> None:
        result = runner.invoke(app, ["version"])
        self.assertIn("Trevvos Forge", result.output)
        self.assertIn("0.1.0-alpha.1", result.output)

    def test_version_flag_exits_zero(self) -> None:
        result = runner.invoke(app, ["--version"])
        self.assertEqual(result.exit_code, 0, result.output)

    def test_version_flag_prints_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        self.assertIn("0.1.0-alpha.1", result.output)


# ---------------------------------------------------------------------------
# 10. Entry point is importable
# ---------------------------------------------------------------------------

class TestEntryPoint(unittest.TestCase):
    def test_entry_point_imports_main(self) -> None:
        text = _read("packaging/trevvos_entry.py")
        self.assertIn("from trevvos_forge.cli import main", text)

    def test_entry_point_calls_main(self) -> None:
        text = _read("packaging/trevvos_entry.py")
        self.assertIn("main()", text)

    def test_entry_point_has_freeze_support(self) -> None:
        text = _read("packaging/trevvos_entry.py")
        self.assertIn("freeze_support", text)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
