import subprocess
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.diff_builder import build_unified_diff_from_file_changes
from trevvos_forge.exceptions import DiffError
from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput
from trevvos_forge.operation_applier import apply_operation_change
from trevvos_forge.sessions import write_patch_file


class OperationApplierTests(unittest.TestCase):
    def test_insert_after_heading(self) -> None:
        original = "# Trevvos Forge\n\nA CLI for local AI-assisted engineering.\n"
        expected = (
            "# Trevvos Forge\n\n"
            "Local-first AI engineering assistant powered by local LLMs.\n\n"
            "A CLI for local AI-assisted engineering.\n"
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text(original, encoding="utf-8")

            result = apply_operation_change(
                FileChange(
                    path="README.md",
                    change_type="modified",
                    content=None,
                    mode="operation_based_edit",
                    operation="insert_after_heading",
                    target="# Trevvos Forge",
                    insert="Local-first AI engineering assistant powered by local LLMs.",
                ),
                root,
            )

            self.assertEqual(result.new_content, expected)

    def test_insert_after_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sample.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

            result = apply_operation_change(
                FileChange(
                    path="sample.txt",
                    change_type="modified",
                    content=None,
                    mode="operation_based_edit",
                    operation="insert_after_line",
                    target="beta",
                    insert="inserted",
                ),
                root,
            )

            self.assertEqual(result.new_content, "alpha\nbeta\ninserted\ngamma\n")

    def test_insert_before_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text(
                "# Trevvos Forge\n\n## Usage\n\nRun trevvos.\n",
                encoding="utf-8",
            )

            result = apply_operation_change(
                FileChange(
                    path="README.md",
                    change_type="modified",
                    content=None,
                    mode="operation_based_edit",
                    operation="insert_before_line",
                    target="## Usage",
                    insert="## Installation\n\nRun `pip install trevvos-forge`.\n\n",
                ),
                root,
            )

            self.assertEqual(
                result.new_content,
                "# Trevvos Forge\n\n"
                "## Installation\n\n"
                "Run `pip install trevvos-forge`.\n\n"
                "## Usage\n\n"
                "Run trevvos.\n",
            )

    def test_replace_exact_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sample.txt").write_text("hello old world\n", encoding="utf-8")

            result = apply_operation_change(
                FileChange(
                    path="sample.txt",
                    change_type="modified",
                    content=None,
                    mode="operation_based_edit",
                    operation="replace_exact_text",
                    target="old",
                    replacement="new",
                ),
                root,
            )

            self.assertEqual(result.new_content, "hello new world\n")

    def test_replace_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "example.py").write_text(
                'def hello():\n    return "old"\n\n'
                'def untouched():\n    return "same"\n',
                encoding="utf-8",
            )

            result = apply_operation_change(
                FileChange(
                    path="example.py",
                    change_type="modified",
                    content=None,
                    mode="operation_based_edit",
                    operation="replace_block",
                    target='def hello():\n    return "old"\n',
                    replacement='def hello():\n    return "new"\n',
                ),
                root,
            )

            self.assertEqual(
                result.new_content,
                'def hello():\n    return "new"\n\n'
                'def untouched():\n    return "same"\n',
            )

    def test_append_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Trevvos Forge\n", encoding="utf-8")

            result = apply_operation_change(
                FileChange(
                    path="README.md",
                    change_type="modified",
                    content=None,
                    mode="operation_based_edit",
                    operation="append_to_file",
                    insert="\n\n## License\n\nMIT\n",
                ),
                root,
            )

            self.assertEqual(result.new_content, "# Trevvos Forge\n\n## License\n\nMIT\n")

    def test_create_file_diff_passes_git_apply_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            patch = build_unified_diff_from_file_changes(
                workspace_root=root,
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="docs/usage.md",
                            change_type="created",
                            content="# Usage\n\nHello.\n",
                            mode="operation_based_edit",
                            operation="create_file",
                        )
                    ]
                ),
            )
            patch_path = root / "diff.patch"
            write_patch_file(patch_path, patch)

            result = subprocess.run(
                ["git", "apply", "--check", str(patch_path)],
                cwd=root,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_heading_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Other\n", encoding="utf-8")

            with self.assertRaisesRegex(DiffError, "target not found"):
                apply_operation_change(
                    FileChange(
                        path="README.md",
                        change_type="modified",
                        content=None,
                        mode="operation_based_edit",
                        operation="insert_after_heading",
                        target="# Trevvos Forge",
                        insert="text",
                    ),
                    root,
                )

    def test_ambiguous_insert_after_line_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "sample.txt").write_text("same\nmiddle\nsame\n", encoding="utf-8")

            with self.assertRaisesRegex(DiffError, "ambiguous"):
                apply_operation_change(
                    FileChange(
                        path="sample.txt",
                        change_type="modified",
                        content=None,
                        mode="operation_based_edit",
                        operation="insert_after_line",
                        target="same",
                        insert="text",
                    ),
                    root,
                )

    def test_missing_insert_before_line_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Trevvos Forge\n", encoding="utf-8")

            with self.assertRaisesRegex(DiffError, "target not found"):
                apply_operation_change(
                    FileChange(
                        path="README.md",
                        change_type="modified",
                        content=None,
                        mode="operation_based_edit",
                        operation="insert_before_line",
                        target="## Usage",
                        insert="text",
                    ),
                    root,
                )

    def test_ambiguous_replace_block_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "example.py").write_text(
                'def duplicated():\n    return "same"\n\n'
                'def duplicated():\n    return "same"\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(DiffError, "ambiguous"):
                apply_operation_change(
                    FileChange(
                        path="example.py",
                        change_type="modified",
                        content=None,
                        mode="operation_based_edit",
                        operation="replace_block",
                        target='def duplicated():\n    return "same"\n',
                        replacement='def duplicated():\n    return "new"\n',
                    ),
                    root,
                )

    def test_legacy_full_file_rewrite_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Old\n", encoding="utf-8")

            patch = build_unified_diff_from_file_changes(
                workspace_root=root,
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="README.md",
                            change_type="modified",
                            content="# New\n",
                            mode="full_file_rewrite",
                        )
                    ]
                ),
            )

            self.assertIn("+# New", patch)


if __name__ == "__main__":
    unittest.main()
