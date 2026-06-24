"""Smoke tests for Advisory Mode — no real LLM calls."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app

FAKE_ADVISORY_RESPONSE = "# Fake Advisory\n\nThis is a deterministic fake response for smoke testing.\n"

runner = CliRunner()


def _sample_repo(root: Path) -> Path:
    _git(root, ["init"])
    _git(root, ["config", "user.email", "test@example.com"])
    _git(root, ["config", "user.name", "Test User"])
    (root / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def subtract(a, b):\n    return a - b\n\n"
        "def multiply(a, b):\n    return a * b\n\n"
        "def divide(a, b):\n"
        "    if b == 0:\n"
        "        raise ValueError('Cannot divide by zero')\n"
        "    return a / b\n",
        encoding="utf-8",
    )
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_calculator.py").write_text(
        "import unittest\nfrom calculator import divide\n\n"
        "class TestCalculator(unittest.TestCase):\n"
        "    def test_divide_by_zero_raises_value_error(self):\n"
        "        with self.assertRaises(ValueError):\n"
        "            divide(10, 0)\n",
        encoding="utf-8",
    )
    _git(root, ["add", "."])
    _git(root, ["commit", "-m", "initial"])
    return root


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _patch_provider():
    """Context manager: patches trevvos_forge.cli.build_provider to return a fake provider."""
    mock_patcher = patch("trevvos_forge.cli.build_provider")
    return mock_patcher


class AdvisoryInspectSmokeTests(unittest.TestCase):
    def test_inspect_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            result = runner.invoke(app, ["inspect", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue((root / ".trevvos" / "project_profile.json").exists())

    def test_inspect_json_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            result = runner.invoke(app, ["inspect", "--json", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            # output should be valid JSON
            profile = json.loads(result.output.strip())
            self.assertIsInstance(profile, dict)

    def test_inspect_file_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            result = runner.invoke(app, ["inspect", "calculator.py", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("def add", result.output)


class AdvisoryAnalyzeSmokeTests(unittest.TestCase):
    def test_analyze_exits_zero_and_saves_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["analyze", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            # Find the session with analysis_report.md
            sessions_dir = root / ".trevvos" / "sessions"
            reports = list(sessions_dir.glob("*/analysis_report.md"))
            self.assertTrue(len(reports) >= 1, "analysis_report.md not found")
            meta_files = list(sessions_dir.glob("*/analysis_metadata.json"))
            self.assertTrue(len(meta_files) >= 1)
            meta = json.loads(meta_files[0].read_text())
            self.assertEqual(meta["status"], "succeeded")
            self.assertEqual(meta["command"], "analyze")

    def test_analyze_target_file_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["analyze", "calculator.py", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            sessions_dir = root / ".trevvos" / "sessions"
            reports = list(sessions_dir.glob("*/analysis_report.md"))
            self.assertTrue(len(reports) >= 1)

    def test_analyze_provider_called_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_provider = mock_bp.return_value
                mock_provider.generate.return_value = FAKE_ADVISORY_RESPONSE
                runner.invoke(app, ["analyze", "--path", str(root)])
            mock_provider.generate.assert_called_once()


class AdvisoryExplainSmokeTests(unittest.TestCase):
    def test_explain_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["explain", "calculator.py", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            sessions_dir = root / ".trevvos" / "sessions"
            explanations = list(sessions_dir.glob("*/explanation.md"))
            self.assertTrue(len(explanations) >= 1)
            meta_files = list(sessions_dir.glob("*/explanation_metadata.json"))
            self.assertTrue(len(meta_files) >= 1)
            meta = json.loads(meta_files[0].read_text())
            self.assertEqual(meta["status"], "succeeded")

    def test_explain_with_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(
                    app, ["explain", "calculator.py", "--symbol", "divide", "--path", str(root)]
                )
            self.assertEqual(result.exit_code, 0, result.output)

    def test_explain_with_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(
                    app, ["explain", "calculator.py", "--flow", "--path", str(root)]
                )
            self.assertEqual(result.exit_code, 0, result.output)


class AdvisoryProposeSmokeTests(unittest.TestCase):
    def test_propose_exits_zero_and_saves_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(
                    app,
                    ["propose", "add power function to calculator", "--path", str(root)],
                )
            self.assertEqual(result.exit_code, 0, result.output)
            sessions_dir = root / ".trevvos" / "sessions"
            proposals = list(sessions_dir.glob("*/proposal.md"))
            self.assertTrue(len(proposals) >= 1)
            meta_files = list(sessions_dir.glob("*/proposal_metadata.json"))
            self.assertTrue(len(meta_files) >= 1)
            meta = json.loads(meta_files[0].read_text())
            self.assertEqual(meta["status"], "succeeded")
            self.assertEqual(meta["command"], "propose")


class AdvisorySpecSmokeTests(unittest.TestCase):
    def test_spec_exits_zero_and_saves_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(
                    app,
                    ["spec", "add power function to calculator", "--path", str(root)],
                )
            self.assertEqual(result.exit_code, 0, result.output)
            sessions_dir = root / ".trevvos" / "sessions"
            specs = list(sessions_dir.glob("*/handoff_spec.md"))
            self.assertTrue(len(specs) >= 1, "handoff_spec.md not found")
            prompts = list(sessions_dir.glob("*/external_ai_prompt.md"))
            self.assertTrue(len(prompts) >= 1, "external_ai_prompt.md not found")
            meta_files = list(sessions_dir.glob("*/handoff_metadata.json"))
            self.assertTrue(len(meta_files) >= 1)
            meta = json.loads(meta_files[0].read_text())
            self.assertEqual(meta["status"], "succeeded")


class AdvisoryReviewDiffSmokeTests(unittest.TestCase):
    def test_review_diff_with_modified_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            # Modify a tracked file to create a diff
            (root / "calculator.py").write_text(
                "def add(a, b):\n    return a + b\n\ndef power(base, exp):\n    return base ** exp\n",
                encoding="utf-8",
            )
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["review-diff", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            sessions_dir = root / ".trevvos" / "sessions"
            reviews = list(sessions_dir.glob("*/diff_review.md"))
            self.assertTrue(len(reviews) >= 1, "diff_review.md not found")
            meta_files = list(sessions_dir.glob("*/diff_review_metadata.json"))
            self.assertTrue(len(meta_files) >= 1)
            meta = json.loads(meta_files[0].read_text())
            self.assertEqual(meta["status"], "succeeded")
            self.assertEqual(meta["command"], "review-diff")

    def test_review_diff_with_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            # Create an untracked Python file — should be included in review context
            (root / "new_feature.py").write_text(
                "def power(base, exp):\n    return base ** exp\n",
                encoding="utf-8",
            )
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["review-diff", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            sessions_dir = root / ".trevvos" / "sessions"
            untracked_files = list(sessions_dir.glob("*/untracked_files.json"))
            self.assertTrue(len(untracked_files) >= 1, "untracked_files.json not found")
            payload = json.loads(untracked_files[0].read_text())
            # new_feature.py should appear in included
            included_paths = [item["path"] for item in payload.get("included", [])]
            self.assertIn("new_feature.py", included_paths)

    def test_review_diff_staged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            # Stage a change
            (root / "calculator.py").write_text(
                "def add(a, b):\n    return a + b\n\n# staged change\n",
                encoding="utf-8",
            )
            _git(root, ["add", "calculator.py"])
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["review-diff", "--staged", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            sessions_dir = root / ".trevvos" / "sessions"
            reviews = list(sessions_dir.glob("*/diff_review.md"))
            self.assertTrue(len(reviews) >= 1)
            meta_files = list(sessions_dir.glob("*/diff_review_metadata.json"))
            meta = json.loads(meta_files[0].read_text())
            self.assertTrue(meta["staged"])

    def test_review_diff_no_changes_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            # Clean repo: no diff, no untracked — should print info and exit 0
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["review-diff", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            # Provider should NOT be called (nothing to review)
            mock_bp.return_value.generate.assert_not_called()


class AdvisoryTimingTests(unittest.TestCase):
    """Verify that timing output is present in human-readable commands."""

    def _modified_repo(self, root: Path) -> Path:
        root = _sample_repo(root)
        (root / "calculator.py").write_text(
            "def add(a, b):\n    return a + b\n\ndef power(base, exp):\n    return base ** exp\n",
            encoding="utf-8",
        )
        return root

    def test_analyze_output_contains_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["analyze", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Duration:", result.output)

    def test_analyze_metadata_contains_duration_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                runner.invoke(app, ["analyze", "--path", str(root)])
            meta = json.loads(
                next((root / ".trevvos" / "sessions").glob("*/analysis_metadata.json")).read_text()
            )
            self.assertIn("duration_seconds", meta)
            self.assertIsInstance(meta["duration_seconds"], (int, float))

    def test_analyze_json_output_contains_duration_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["analyze", "--json", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            data = json.loads(result.output.strip())
            self.assertIn("duration_seconds", data)

    def test_analyze_json_output_has_no_plain_duration_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["analyze", "--json", "--path", str(root)])
            self.assertEqual(result.exit_code, 0)
            # Output must be parseable as JSON (no extra text)
            json.loads(result.output.strip())

    def test_propose_output_contains_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(
                    app, ["propose", "add power function", "--path", str(root)]
                )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Duration:", result.output)

    def test_propose_metadata_contains_duration_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                runner.invoke(app, ["propose", "add power function", "--path", str(root)])
            meta = json.loads(
                next((root / ".trevvos" / "sessions").glob("*/proposal_metadata.json")).read_text()
            )
            self.assertIn("duration_seconds", meta)

    def test_spec_output_contains_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(
                    app, ["spec", "add power function", "--path", str(root)]
                )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Duration:", result.output)

    def test_spec_metadata_contains_duration_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                runner.invoke(app, ["spec", "add power function", "--path", str(root)])
            meta = json.loads(
                next((root / ".trevvos" / "sessions").glob("*/handoff_metadata.json")).read_text()
            )
            self.assertIn("duration_seconds", meta)

    def test_review_diff_output_contains_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._modified_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                result = runner.invoke(app, ["review-diff", "--path", str(root)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Duration:", result.output)

    def test_review_diff_metadata_contains_duration_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._modified_repo(Path(tmp))
            with _patch_provider() as mock_bp:
                mock_bp.return_value.generate.return_value = FAKE_ADVISORY_RESPONSE
                runner.invoke(app, ["review-diff", "--path", str(root)])
            meta = json.loads(
                next((root / ".trevvos" / "sessions").glob("*/diff_review_metadata.json")).read_text()
            )
            self.assertIn("duration_seconds", meta)


if __name__ == "__main__":
    unittest.main()
