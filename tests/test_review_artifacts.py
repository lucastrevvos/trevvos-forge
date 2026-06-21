import tempfile
import unittest
from pathlib import Path

from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput
from trevvos_forge.review_artifacts import (
    SEMANTIC_REVIEW_NOTE,
    build_change_summary_markdown,
    build_patch_preview,
    build_semantic_review_json,
)
from trevvos_forge.sessions import create_session, write_session_json, write_session_text


class ReviewArtifactsTests(unittest.TestCase):
    def test_change_summary_without_warnings(self) -> None:
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

        summary = build_change_summary_markdown(
            request="Update README",
            file_changes=file_changes,
            warnings=[],
        )

        self.assertIn("# Change Summary", summary)
        self.assertIn("README.md", summary)
        self.assertIn("operation_based_edit", summary)
        self.assertIn("insert_after_heading", summary)
        self.assertIn("Forge safety validation: passed", summary)
        self.assertIn("git apply --check: passed", summary)
        self.assertIn("## Warnings", summary)
        self.assertIn("- None", summary)

    def test_change_summary_with_warnings(self) -> None:
        file_changes = FileChangesOutput(
            changes=[
                FileChange(
                    path="README.md",
                    change_type="modified",
                    content="# README\n",
                    mode="full_file_rewrite",
                )
            ]
        )

        summary = build_change_summary_markdown(
            request="Update README",
            file_changes=file_changes,
            warnings=["LLM output appears truncated..."],
        )

        self.assertIn("LLM output appears truncated...", summary)

    def test_semantic_review_json(self) -> None:
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

        review = build_semantic_review_json(
            request="Update README",
            file_changes=file_changes,
            warnings=["warning"],
        )

        self.assertEqual(review["review_type"], "deterministic")
        self.assertEqual(review["status"], "informational")
        self.assertEqual(review["files_changed"][0]["path"], "README.md")
        self.assertEqual(review["validations"]["safety_validation"], "passed")
        self.assertEqual(review["validations"]["git_apply_check"], "passed")
        self.assertEqual(review["warnings"], ["warning"])
        self.assertIn(SEMANTIC_REVIEW_NOTE, review["notes"])

    def test_patch_preview_short(self) -> None:
        preview, truncated = build_patch_preview("a\nb\nc\n", max_lines=5)

        self.assertEqual(preview, "a\nb\nc")
        self.assertFalse(truncated)

    def test_patch_preview_truncated(self) -> None:
        preview, truncated = build_patch_preview("1\n2\n3\n4\n", max_lines=2)

        self.assertEqual(preview, "1\n2")
        self.assertTrue(truncated)

    def test_diff_artifacts_can_be_saved_to_session(self) -> None:
        file_changes = FileChangesOutput(
            changes=[
                FileChange(
                    path="README.md",
                    change_type="modified",
                    content="# README\n",
                    mode="full_file_rewrite",
                )
            ]
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "Update README", "test")

            write_session_text(session, "diff.patch", "diff --git a/README.md b/README.md\n")
            write_session_text(
                session,
                "change_summary.md",
                build_change_summary_markdown(
                    request="Update README",
                    file_changes=file_changes,
                    warnings=["warning"],
                ),
            )
            write_session_json(
                session,
                "semantic_review.json",
                build_semantic_review_json(
                    request="Update README",
                    file_changes=file_changes,
                    warnings=["warning"],
                ),
            )
            write_session_json(session, "diff_warnings.json", {"warnings": ["warning"]})

            self.assertTrue((session.path / "diff.patch").exists())
            self.assertTrue((session.path / "change_summary.md").exists())
            self.assertTrue((session.path / "semantic_review.json").exists())
            self.assertTrue((session.path / "diff_warnings.json").exists())


if __name__ == "__main__":
    unittest.main()
