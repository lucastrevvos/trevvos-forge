import tempfile
import unittest
from pathlib import Path

from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput
from trevvos_forge.review_artifacts import (
    SEMANTIC_REVIEW_NOTE,
    build_change_summary_markdown,
    build_patch_preview,
    build_semantic_review_json,
    render_deterministic_review_text,
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
        self.assertIn("plan_review", review)
        self.assertIn("test_evidence", review)
        self.assertIn("plan_constraints", review)
        self.assertIn("concerns", review)
        self.assertIn("warning", review["warnings"])
        self.assertIn("No acceptance criteria were available in the plan.", review["warnings"])
        self.assertIn(SEMANTIC_REVIEW_NOTE, review["notes"])

    def test_semantic_review_warns_when_plan_commands_were_not_run(self) -> None:
        file_changes = FileChangesOutput(
            changes=[
                FileChange(
                    path="main.py",
                    change_type="created",
                    content="print('ok')\n",
                    mode="full_file_rewrite",
                )
            ]
        )

        review = build_semantic_review_json(
            request="Create CLI",
            file_changes=file_changes,
            warnings=[],
            plan={
                "expected_behavior": ["python main.py prints ok"],
                "acceptance_criteria": ["CLI runs"],
                "suggested_verification_commands": ["python main.py"],
            },
        )

        self.assertEqual(review["plan_review"]["plan_commands_executed"], "no")
        self.assertIn(
            "Suggested verification commands exist, but sandbox tests were not run.",
            review["warnings"],
        )
        self.assertIn(
            "Plan verification commands were not fully executed.",
            review["warnings"],
        )

    def test_semantic_review_detects_plan_commands_executed(self) -> None:
        file_changes = FileChangesOutput(
            changes=[
                FileChange(
                    path="main.py",
                    change_type="created",
                    content="print('ok')\n",
                    mode="full_file_rewrite",
                )
            ]
        )

        review = build_semantic_review_json(
            request="Create CLI",
            file_changes=file_changes,
            warnings=[],
            plan={
                "acceptance_criteria": ["CLI runs"],
                "suggested_verification_commands": ["python main.py"],
            },
            sandbox_test_results={
                "mode": "sandbox",
                "status": "passed",
                "command_sources": {
                    "plan": ["python main.py"],
                    "executed": ["python main.py"],
                },
            },
        )

        self.assertEqual(review["plan_review"]["plan_commands_executed"], "yes")
        self.assertNotIn(
            "Plan verification commands were not fully executed.",
            review["warnings"],
        )

    def test_semantic_review_concerns_for_failed_tests_and_constraints(self) -> None:
        file_changes = FileChangesOutput(
            changes=[
                FileChange(
                    path="calculator.py",
                    change_type="modified",
                    content="",
                    mode="full_file_rewrite",
                )
            ]
        )

        review = build_semantic_review_json(
            request="Do not modify calculator.py",
            file_changes=file_changes,
            warnings=[],
            plan={"acceptance_criteria": ["Respect plan constraints"]},
            plan_constraints_check={"status": "failed"},
            sandbox_test_results={"mode": "sandbox", "status": "failed"},
            working_tree_test_results={"mode": "working_tree", "status": "failed"},
        )

        self.assertIn("Sandbox tests failed.", review["concerns"])
        self.assertIn("Working tree tests failed.", review["concerns"])
        self.assertIn("Plan constraints check failed.", review["concerns"])

    def test_semantic_review_concerns_for_failed_verification_coverage(self) -> None:
        file_changes = FileChangesOutput(
            changes=[
                FileChange(
                    path="main.py",
                    change_type="modified",
                    content="print('ok')\n",
                    mode="full_file_rewrite",
                )
            ]
        )

        review = build_semantic_review_json(
            request="Add sqrt CLI",
            file_changes=file_changes,
            warnings=[],
            plan={
                "acceptance_criteria": ["sqrt command runs"],
                "expected_behavior": ["python main.py sqrt 9 prints 3.0"],
                "suggested_verification_commands": ["python -m py_compile main.py"],
            },
            verification_coverage={
                "status": "failed",
                "missing": ["python main.py sqrt 9"],
            },
        )

        self.assertIn(
            "Expected behavior command `python main.py sqrt 9` is not covered by suggested verification commands.",
            review["concerns"],
        )

    def test_render_deterministic_review_text_contains_sections(self) -> None:
        text = render_deterministic_review_text(
            {
                "plan_review": {
                    "expected_behavior_count": 2,
                    "acceptance_criteria_count": 1,
                    "suggested_verification_commands_count": 1,
                    "plan_commands_executed": "yes",
                },
                "test_evidence": {
                    "sandbox": "passed",
                    "working_tree": "passed",
                },
                "plan_constraints": {"status": "passed"},
                "concerns": [],
                "warnings": [],
            }
        )

        self.assertIn("Plan evidence", text)
        self.assertIn("Test evidence", text)
        self.assertIn("Plan constraints", text)
        self.assertIn("Concerns", text)
        self.assertIn("Warnings", text)

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
