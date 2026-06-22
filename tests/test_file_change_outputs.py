import json
import unittest

from trevvos_forge.exceptions import FileChangeOutputError
from trevvos_forge.file_change_outputs import ALLOWED_OPERATION_BASED_EDIT_OPERATIONS, parse_file_changes_output


class FileChangeOutputsTests(unittest.TestCase):
    def test_missing_mode_defaults_to_full_file_rewrite(self) -> None:
        output = parse_file_changes_output(
            json.dumps(
                {
                    "changes": [
                        {
                            "path": "README.md",
                            "change_type": "modified",
                            "content": "# README\n",
                        }
                    ]
                }
            )
        )

        self.assertEqual(output.changes[0].mode, "full_file_rewrite")

    def test_unknown_operation_fails(self) -> None:
        with self.assertRaisesRegex(FileChangeOutputError, "Unknown operation"):
            parse_file_changes_output(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "README.md",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "do_magic",
                            }
                        ]
                    }
                )
            )

    def test_operation_full_file_rewrite_with_content_is_normalized(self) -> None:
        output = parse_file_changes_output(
            json.dumps(
                {
                    "changes": [
                        {
                            "path": "main.py",
                            "change_type": "modified",
                            "mode": "operation_based_edit",
                            "operation": "full_file_rewrite",
                            "content": "print('hello')\n",
                        }
                    ]
                }
            )
        )

        change = output.changes[0]
        self.assertEqual(change.mode, "full_file_rewrite")
        self.assertIsNone(change.operation)
        self.assertEqual(change.content, "print('hello')\n")

    def test_operation_full_file_rewrite_without_mode_is_normalized(self) -> None:
        output = parse_file_changes_output(
            json.dumps(
                {
                    "changes": [
                        {
                            "path": "main.py",
                            "change_type": "modified",
                            "operation": "full_file_rewrite",
                            "content": "print('hello')\n",
                        }
                    ]
                }
            )
        )

        change = output.changes[0]
        self.assertEqual(change.mode, "full_file_rewrite")
        self.assertIsNone(change.operation)
        self.assertEqual(change.content, "print('hello')\n")

    def test_operation_full_file_rewrite_without_content_fails_clearly(self) -> None:
        with self.assertRaisesRegex(
            FileChangeOutputError,
            "full_file_rewrite must be used as mode with content",
        ):
            parse_file_changes_output(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "main.py",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "full_file_rewrite",
                            }
                        ]
                    }
                )
            )

    def test_full_file_rewrite_is_not_an_allowed_operation(self) -> None:
        self.assertNotIn("full_file_rewrite", ALLOWED_OPERATION_BASED_EDIT_OPERATIONS)

    def test_insert_operation_requires_target_and_insert(self) -> None:
        with self.assertRaisesRegex(FileChangeOutputError, "target"):
            parse_file_changes_output(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "README.md",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "insert_after_heading",
                                "insert": "text",
                            }
                        ]
                    }
                )
            )

    def test_insert_before_line_requires_target_and_insert(self) -> None:
        with self.assertRaisesRegex(FileChangeOutputError, "target"):
            parse_file_changes_output(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "README.md",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "insert_before_line",
                                "insert": "text",
                            }
                        ]
                    }
                )
            )

        with self.assertRaisesRegex(FileChangeOutputError, "insert"):
            parse_file_changes_output(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "README.md",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "insert_before_line",
                                "target": "## Usage",
                            }
                        ]
                    }
                )
            )

    def test_replace_block_requires_target_and_replacement(self) -> None:
        with self.assertRaisesRegex(FileChangeOutputError, "target"):
            parse_file_changes_output(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "example.py",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "replace_block",
                                "replacement": "new",
                            }
                        ]
                    }
                )
            )

        with self.assertRaisesRegex(FileChangeOutputError, "replacement"):
            parse_file_changes_output(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "example.py",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "replace_block",
                                "target": "old",
                            }
                        ]
                    }
                )
            )

    def test_append_to_file_requires_insert(self) -> None:
        with self.assertRaisesRegex(FileChangeOutputError, "insert"):
            parse_file_changes_output(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "README.md",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "append_to_file",
                            }
                        ]
                    }
                )
            )


if __name__ == "__main__":
    unittest.main()
