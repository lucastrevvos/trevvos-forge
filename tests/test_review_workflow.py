import json
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.review_workflow import (
    build_review_context,
    build_semantic_review_prompt,
    parse_llm_review_response,
    render_llm_review_markdown,
    write_llm_review_artifacts,
)
from trevvos_forge.sessions import write_patch_file


class ReviewWorkflowTests(unittest.TestCase):
    def test_build_review_context_with_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            _write_review_fixture(session_dir)
            write_patch_file(
                session_dir / "diff.patch",
                "\n".join(f"line {index}" for index in range(10)),
            )
            (session_dir / "test_output.log").write_text(
                "\n".join(f"log {index}" for index in range(10)),
                encoding="utf-8",
            )

            context = build_review_context(
                session_dir,
                max_patch_lines=3,
                max_test_log_lines=4,
            )

            self.assertIn("diff.patch", context["evidence_used"])
            self.assertIn("change_summary.md", context["evidence_used"])
            self.assertIn("semantic_review.json", context["evidence_used"])
            self.assertIn("test_results.json", context["evidence_used"])
            self.assertIn("diff_warnings.json", context["evidence_used"])
            self.assertEqual(context["plan"]["acceptance_criteria"], [])
            self.assertEqual(context["patch_preview"], "line 0\nline 1\nline 2")
            self.assertTrue(context["patch_preview_truncated"])
            self.assertEqual(context["test_output_tail"], "log 6\nlog 7\nlog 8\nlog 9")
            self.assertTrue(context["test_output_truncated"])
            self.assertEqual(context["warnings"], ["review this"])

    def test_build_review_context_without_test_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            write_patch_file(session_dir / "diff.patch", "diff --git a/a b/a\n")

            context = build_review_context(session_dir)

            self.assertFalse(context["test_results_available"])
            self.assertIsNone(context["test_results"])
            self.assertNotIn("test_results.json", context["evidence_used"])

    def test_build_review_context_includes_sandbox_and_working_tree_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            (session_dir / "sandbox_test_results.json").write_text(
                json.dumps({"mode": "sandbox", "status": "passed"}),
                encoding="utf-8",
            )
            (session_dir / "working_tree_test_results.json").write_text(
                json.dumps({"mode": "working_tree", "status": "passed"}),
                encoding="utf-8",
            )
            (session_dir / "sandbox_test_output.log").write_text("sandbox ok\n", encoding="utf-8")
            (session_dir / "working_tree_test_output.log").write_text("working ok\n", encoding="utf-8")

            context = build_review_context(session_dir)

            self.assertTrue(context["test_results_available"])
            self.assertEqual(context["sandbox_test_results"]["status"], "passed")
            self.assertEqual(context["working_tree_test_results"]["status"], "passed")
            self.assertIn("sandbox_test_results.json", context["evidence_used"])
            self.assertIn("working_tree_test_results.json", context["evidence_used"])
            self.assertEqual(context["sandbox_test_output_tail"], "sandbox ok")
            self.assertEqual(context["working_tree_test_output_tail"], "working ok")

    def test_build_review_context_includes_plan_fields_and_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            (session_dir / "plan.json").write_text(
                json.dumps(
                    {
                        "expected_behavior": ["python main.py add 2 3 prints 5"],
                        "acceptance_criteria": ["Uses argparse"],
                        "suggested_verification_commands": ["python main.py add 2 3"],
                        "files_to_create": ["main.py"],
                        "files_to_modify": [],
                        "files_not_to_modify": ["calculator.py"],
                    }
                ),
                encoding="utf-8",
            )
            (session_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
            (session_dir / "plan_constraints_check.json").write_text(
                json.dumps({"status": "passed"}),
                encoding="utf-8",
            )

            context = build_review_context(session_dir)

            self.assertEqual(
                context["plan"]["expected_behavior"],
                ["python main.py add 2 3 prints 5"],
            )
            self.assertEqual(context["plan"]["acceptance_criteria"], ["Uses argparse"])
            self.assertEqual(
                context["plan"]["suggested_verification_commands"],
                ["python main.py add 2 3"],
            )
            self.assertEqual(context["plan_constraints_check"]["status"], "passed")
            self.assertIn("plan.json", context["evidence_used"])
            self.assertIn("plan_constraints_check.json", context["evidence_used"])

    def test_build_review_context_legacy_sandbox_test_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            (session_dir / "test_results.json").write_text(
                json.dumps({"mode": "sandbox", "status": "passed"}),
                encoding="utf-8",
            )

            context = build_review_context(session_dir)

            self.assertEqual(context["sandbox_test_results"]["status"], "passed")
            self.assertIsNone(context["working_tree_test_results"])

    def test_build_review_context_legacy_working_tree_test_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            (session_dir / "test_results.json").write_text(
                json.dumps({"mode": "working_tree", "status": "passed"}),
                encoding="utf-8",
            )

            context = build_review_context(session_dir)

            self.assertEqual(context["working_tree_test_results"]["status"], "passed")
            self.assertIsNone(context["sandbox_test_results"])

    def test_parse_plain_json(self) -> None:
        review = parse_llm_review_response(
            json.dumps(
                {
                    "verdict": "appears_ok",
                    "confidence": "medium",
                    "request_alignment": "appears_aligned",
                    "risk_level": "low",
                    "summary": "Looks aligned.",
                    "risks": [],
                    "suggested_checks": ["Read the diff."],
                    "evidence_used": ["diff.patch"],
                    "notes": [],
                }
            )
        )

        self.assertEqual(review["status"], "informational")
        self.assertEqual(review["verdict"], "appears_ok")
        self.assertEqual(review["risk_level"], "low")
        self.assertEqual(review["acceptance_criteria_alignment"], "unknown")
        self.assertEqual(review["verification_evidence"], "unknown")

    def test_parse_plain_json_with_acceptance_and_evidence_fields(self) -> None:
        review = parse_llm_review_response(
            json.dumps(
                {
                    "verdict": "has_concerns",
                    "confidence": "medium",
                    "request_alignment": "partially_aligned",
                    "acceptance_criteria_alignment": "partially_satisfied",
                    "verification_evidence": "partial",
                    "risk_level": "medium",
                    "summary": "Some criteria need evidence.",
                    "risks": [],
                    "concerns": ["Plan commands were not run."],
                    "suggested_checks": ["Run sandbox tests."],
                    "missing_evidence": ["sandbox_test_results.json"],
                    "evidence_used": ["diff.patch"],
                    "notes": [],
                }
            )
        )

        self.assertEqual(review["acceptance_criteria_alignment"], "partially_satisfied")
        self.assertEqual(review["verification_evidence"], "partial")
        self.assertEqual(review["concerns"], ["Plan commands were not run."])
        self.assertEqual(review["missing_evidence"], ["sandbox_test_results.json"])

    def test_build_semantic_review_prompt_includes_plan_evidence(self) -> None:
        prompt = build_semantic_review_prompt(
            {
                "plan": {
                    "expected_behavior": ["python main.py add 2 3 prints 5"],
                    "acceptance_criteria": ["Uses argparse"],
                    "suggested_verification_commands": ["python main.py add 2 3"],
                },
                "sandbox_test_results": {"status": "passed"},
                "working_tree_test_results": {"status": "not_run"},
                "plan_constraints_check": {"status": "passed"},
            }
        )

        self.assertIn("acceptance_criteria", prompt)
        self.assertIn("expected_behavior", prompt)
        self.assertIn("suggested_verification_commands", prompt)
        self.assertIn("sandbox_test_results", prompt)
        self.assertIn("working_tree_test_results", prompt)

    def test_parse_json_inside_markdown(self) -> None:
        raw = """Here is the review:

```json
{"verdict":"has_concerns","confidence":"low","request_alignment":"unknown","risk_level":"medium","summary":"Check manually.","risks":["Missing tests"],"suggested_checks":["Run tests"],"evidence_used":["diff.patch"],"notes":[]}
```
"""

        review = parse_llm_review_response(raw)

        self.assertEqual(review["verdict"], "has_concerns")
        self.assertEqual(review["risk_level"], "medium")
        self.assertIn("Missing tests", review["risks"])

    def test_parse_failure_returns_parse_failed_review(self) -> None:
        review = parse_llm_review_response("not json")

        self.assertEqual(review["status"], "parse_failed")
        self.assertEqual(review["verdict"], "needs_human_review")
        self.assertEqual(review["request_alignment"], "unknown")

    def test_render_markdown(self) -> None:
        markdown = render_llm_review_markdown(
            {
                "verdict": "needs_human_review",
                "summary": "Review manually.",
                "request_alignment": "appears_aligned",
                "risk_level": "low",
                "risks": ["Risk"],
                "suggested_checks": ["Check"],
                "evidence_used": ["diff.patch"],
                "notes": ["Note"],
            }
        )

        self.assertIn("# LLM Review", markdown)
        self.assertIn("needs_human_review", markdown)
        self.assertIn("Risk", markdown)
        self.assertIn("Check", markdown)
        self.assertIn("does not prove semantic correctness", markdown)

    def test_write_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            review = parse_llm_review_response("{}")
            markdown = render_llm_review_markdown(review)

            write_llm_review_artifacts(
                session_dir=session_dir,
                review=review,
                markdown=markdown,
                raw_text="raw response",
            )

            self.assertTrue((session_dir / "llm_review.md").exists())
            self.assertTrue((session_dir / "llm_review.json").exists())
            self.assertTrue((session_dir / "llm_review_raw.txt").exists())


def _write_review_fixture(session_dir: Path) -> None:
    (session_dir / "user_request.txt").write_text("Change README.", encoding="utf-8")
    (session_dir / "plan.md").write_text("Plan.", encoding="utf-8")
    (session_dir / "change_summary.md").write_text("# Change Summary\n", encoding="utf-8")
    (session_dir / "semantic_review.json").write_text(
        json.dumps(
            {
                "files_changed": [
                    {
                        "path": "README.md",
                        "change_type": "modified",
                        "mode": "operation_based_edit",
                        "operation": "insert_after_heading",
                    }
                ],
                "validations": {
                    "safety_validation": "passed",
                    "git_apply_check": "passed",
                },
            }
        ),
        encoding="utf-8",
    )
    (session_dir / "file_changes.json").write_text(
        json.dumps(
            {
                "changes": [
                    {
                        "path": "README.md",
                        "change_type": "modified",
                        "mode": "operation_based_edit",
                        "operation": "insert_after_heading",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (session_dir / "diff_warnings.json").write_text(
        json.dumps({"warnings": ["review this"]}),
        encoding="utf-8",
    )
    (session_dir / "test_results.json").write_text(
        json.dumps({"status": "passed"}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
