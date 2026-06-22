import subprocess
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.sessions import write_patch_file
from trevvos_forge.diff_builder import build_unified_diff_from_file_changes
from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput


class PatchWriterTests(unittest.TestCase):
    def test_patch_writer_saves_lf_even_with_crlf_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            patch_path = Path(temp_dir) / "diff.patch"
            crlf_text = "line1\r\nline2\rline3\n"
            
            write_patch_file(patch_path, crlf_text)
            
            patch_bytes = patch_path.read_bytes()
            self.assertNotIn(b"\r\n", patch_bytes)
            self.assertNotIn(b"\r", patch_bytes)
            self.assertIn(b"\n", patch_bytes)
            
            # Read text and verify correct content
            self.assertEqual(patch_path.read_text(encoding="utf-8"), "line1\nline2\nline3\n")

    def test_diff_builder_saves_diff_patch_with_lf(self) -> None:
        # Test integration: create a temporary repo, generate a patch, save with helper, check git apply --check
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            
            # Initialize git repo
            subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, capture_output=True, check=True)
            
            # Create a README with LF endings
            readme_path = root / "README.md"
            readme_path.write_bytes(b"# Trevvos Forge\n\nA CLI for local AI-assisted engineering.\n")
            
            subprocess.run(["git", "add", "README.md"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=root, capture_output=True, check=True)
            
            file_changes = FileChangesOutput(
                changes=[
                    FileChange(
                        path="README.md",
                        change_type="modified",
                        content=None,
                        mode="operation_based_edit",
                        operation="insert_after_heading",
                        target="# Trevvos Forge",
                        insert="Local-first AI engineering assistant powered by local LLMs.",
                    )
                ]
            )
            
            patch_text = build_unified_diff_from_file_changes(
                workspace_root=root,
                file_changes=file_changes,
            )
            
            patch_path = root / "diff.patch"
            write_patch_file(patch_path, patch_text)
            
            patch_bytes = patch_path.read_bytes()
            self.assertNotIn(b"\r\n", patch_bytes)
            self.assertIn(b"\n", patch_bytes)
            
            # Check with git apply --check
            result = subprocess.run(
                ["git", "apply", "--check", "diff.patch"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"git apply --check failed: {result.stderr}")
