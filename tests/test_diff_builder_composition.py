import subprocess
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.diff_builder import build_unified_diff_from_file_changes
from trevvos_forge.exceptions import DiffError
from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput
from trevvos_forge.sessions import write_patch_file


class DiffBuilderCompositionTests(unittest.TestCase):
    def test_two_operations_same_file_generate_single_valid_diff(self) -> None:
        original = 'def hello():\n    return "new"\n\n' 'def untouched():\n    return "same"\n'
        expected = (
            "def add(a, b):\n"
            "    return a + b\n\n"
            "def untouched():\n"
            '    return "same"\n\n'
            "def subtract(a, b):\n"
            "    return a - b\n"
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            example_path = root / "example.py"
            example_path.write_text(original, encoding="utf-8")

            patch = build_unified_diff_from_file_changes(
                workspace_root=root,
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="example.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="replace_block",
                            target='def hello():\n    return "new"\n',
                            replacement="def add(a, b):\n    return a + b\n",
                        ),
                        FileChange(
                            path="example.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="append_to_file",
                            insert="\n\ndef subtract(a, b):\n    return a - b\n",
                        ),
                    ]
                ),
            )

            self.assertEqual(patch.count("diff --git a/example.py b/example.py"), 1)
            self._assert_patch_applies(root, patch)
            self.assertEqual(example_path.read_text(encoding="utf-8"), expected)

    def test_real_failure_shape_does_not_generate_duplicate_headers(self) -> None:
        original = 'def hello():\n    return "new"\n\n' 'def untouched():\n    return "same"\n'
        replacement = (
            "def add(a, b):\n"
            "    return a + b\n\n"
            "def subtract(a, b):\n"
            "    return a - b\n\n"
            "def multiply(a, b):\n"
            "    return a * b\n\n"
            "def divide(a, b):\n"
            "    return a / b\n"
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "example.py").write_text(original, encoding="utf-8")

            patch = build_unified_diff_from_file_changes(
                workspace_root=root,
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="example.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="replace_block",
                            target=original,
                            replacement=replacement,
                        ),
                        FileChange(
                            path="example.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="append_to_file",
                            insert="\n\nif __name__ == '__main__':\n    print(add(1, 2))\n",
                        ),
                    ]
                ),
            )

            self.assertEqual(patch.count("diff --git a/example.py b/example.py"), 1)
            self._assert_patch_applies(root, patch)

    def test_multiple_files_still_generate_one_diff_per_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Project\n", encoding="utf-8")
            (root / "example.py").write_text("print('old')\n", encoding="utf-8")

            patch = build_unified_diff_from_file_changes(
                workspace_root=root,
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="README.md",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="append_to_file",
                            insert="\nNotes\n",
                        ),
                        FileChange(
                            path="example.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="replace_exact_text",
                            target="old",
                            replacement="new",
                        ),
                    ]
                ),
            )

            self.assertEqual(patch.count("diff --git a/README.md b/README.md"), 1)
            self.assertEqual(patch.count("diff --git a/example.py b/example.py"), 1)
            self._assert_patch_applies(root, patch)

    def test_mixed_full_rewrite_and_operation_same_file_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Old\n", encoding="utf-8")

            with self.assertRaisesRegex(DiffError, "mixed file change modes"):
                build_unified_diff_from_file_changes(
                    workspace_root=root,
                    file_changes=FileChangesOutput(
                        changes=[
                            FileChange(
                                path="README.md",
                                change_type="modified",
                                content="# New\n",
                                mode="full_file_rewrite",
                            ),
                            FileChange(
                                path="README.md",
                                change_type="modified",
                                content=None,
                                mode="operation_based_edit",
                                operation="append_to_file",
                                insert="More\n",
                            ),
                        ]
                    ),
                )

    def test_create_file_followed_by_append_composes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            patch = build_unified_diff_from_file_changes(
                workspace_root=root,
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="docs/usage.md",
                            change_type="created",
                            content="# Usage\n",
                            mode="operation_based_edit",
                            operation="create_file",
                        ),
                        FileChange(
                            path="docs/usage.md",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="append_to_file",
                            insert="More\n",
                        ),
                    ]
                ),
            )

            self.assertEqual(patch.count("diff --git a/docs/usage.md b/docs/usage.md"), 1)
            self._assert_patch_applies(root, patch)
            self.assertEqual((root / "docs/usage.md").read_text(encoding="utf-8"), "# Usage\nMore\n")

    def test_create_file_after_modification_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text("# Old\n", encoding="utf-8")

            with self.assertRaisesRegex(DiffError, "create_file must be the first operation"):
                build_unified_diff_from_file_changes(
                    workspace_root=root,
                    file_changes=FileChangesOutput(
                        changes=[
                            FileChange(
                                path="README.md",
                                change_type="modified",
                                content=None,
                                mode="operation_based_edit",
                                operation="append_to_file",
                                insert="More\n",
                            ),
                            FileChange(
                                path="README.md",
                                change_type="created",
                                content="# New\n",
                                mode="operation_based_edit",
                                operation="create_file",
                            ),
                        ]
                    ),
                )

    def _assert_patch_applies(self, root: Path, patch: str) -> None:
        patch_path = root / "diff.patch"
        write_patch_file(patch_path, patch)

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


if __name__ == "__main__":
    unittest.main()
