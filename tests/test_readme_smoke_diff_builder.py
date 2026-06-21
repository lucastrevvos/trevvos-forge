import subprocess
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.diff_builder import build_unified_diff_from_file_changes
from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput


class ReadmeSmokeDiffBuilderTests(unittest.TestCase):
    def test_readme_tagline_below_main_heading(self) -> None:
        original = "# Trevvos Forge\n\nA CLI for local AI-assisted engineering.\n"
        expected = (
            "# Trevvos Forge\n\n"
            "Local-first AI engineering assistant powered by local LLMs.\n\n"
            "A CLI for local AI-assisted engineering.\n"
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            readme_path = root / "README.md"
            readme_path.write_text(original, encoding="utf-8")

            patch = build_unified_diff_from_file_changes(
                workspace_root=root,
                file_changes=FileChangesOutput(
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
                ),
            )

            patch_path = root / "diff.patch"
            patch_path.write_text(patch, encoding="utf-8")

            check_result = subprocess.run(
                ["git", "apply", "--check", str(patch_path)],
                cwd=root,
                capture_output=True,
                text=True,
            )

            self.assertEqual(check_result.returncode, 0, check_result.stderr)

            apply_result = subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=root,
                capture_output=True,
                text=True,
            )

            self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
            self.assertEqual(readme_path.read_text(encoding="utf-8"), expected)

    def test_truncated_output_warning_when_tail_is_preserved(self) -> None:
        original = "line 1\nline 2\nline 3\nline 4\n"
        partial_final = "line 1\ninserted\nline 2\n"

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text(original, encoding="utf-8")
            warnings: list[str] = []

            patch = build_unified_diff_from_file_changes(
                workspace_root=root,
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="README.md",
                            change_type="modified",
                            content=partial_final,
                            mode="full_file_rewrite",
                        )
                    ]
                ),
                warnings=warnings,
            )

            self.assertIn("line 3", patch)
            self.assertTrue(warnings)
            self.assertIn("LLM output appears truncated", warnings[0])


if __name__ == "__main__":
    unittest.main()
