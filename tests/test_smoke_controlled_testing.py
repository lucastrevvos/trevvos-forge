"""Smoke tests for Controlled Testing Mode — no real LLM calls."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.exceptions import WorkspaceError
from trevvos_forge.test_apply_workflow import (
    TestApplyRequest,
    find_best_tests_apply_session,
    run_tests_apply_workflow,
)
from trevvos_forge.test_generation_workflow import TestAddRequest, run_tests_add_workflow

runner = CliRunner()


class _FakeProvider:
    def __init__(self, response: str | list[str]) -> None:
        self.responses = [response] if isinstance(response, str) else list(response)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if len(self.responses) == 1:
            return self.responses[0]
        if self.responses:
            return self.responses.pop(0)
        return self.prompts[-1]

    @property
    def call_count(self) -> int:
        return len(self.prompts)


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
    _git(root, ["add", "calculator.py"])
    _git(root, ["commit", "-m", "initial"])
    return root


def _sample_repo_with_tests(root: Path) -> Path:
    """Sample repo that already has a test file for divide."""
    root = _sample_repo(root)
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
    _git(root, ["add", "tests/"])
    _git(root, ["commit", "-m", "add test file"])
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


def _create_divide_test_response() -> str:
    return json.dumps({
        "changes": [{
            "path": "tests/test_calculator.py",
            "change_type": "created",
            "mode": "operation_based_edit",
            "operation": "create_file",
            "content": (
                "import unittest\n\n"
                "from calculator import divide\n\n\n"
                "class TestCalculator(unittest.TestCase):\n"
                "    def test_divide_by_zero_raises_value_error(self):\n"
                "        with self.assertRaises(ValueError):\n"
                "            divide(10, 0)\n"
                "\n"
                "    def test_divide_positive_numbers(self):\n"
                "        self.assertEqual(divide(10, 2), 5.0)\n"
            ),
        }]
    })


def _create_add_test_response() -> str:
    """Response that appends a test for `add` to existing test file."""
    return json.dumps({
        "changes": [{
            "path": "tests/test_calculator.py",
            "change_type": "modified",
            "mode": "operation_based_edit",
            "operation": "append_to_file",
            "insert": (
                "\n\n    def test_add_two_positives(self):\n"
                "        from calculator import add\n"
                "        self.assertEqual(add(1, 2), 3)\n"
            ),
        }]
    })


def _make_add_request(root: Path, **kwargs) -> TestAddRequest:
    defaults = dict(
        repo_root=root,
        source_path="calculator.py",
        symbol="divide",
        all_symbols=False,
        test_file=None,
        unit=False,
        e2e=False,
        write=False,
        yes=False,
        force=False,
        keep_sandbox=False,
        max_generation_retries=1,
        max_structure_retries=1,
        max_sandbox_retries=1,
        timeout=120,
    )
    defaults.update(kwargs)
    return TestAddRequest(**defaults)


class TestsInspectSmokeTests(unittest.TestCase):
    def test_tests_inspect_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            result = runner.invoke(
                app, ["tests", "inspect", "calculator.py", "--path", str(root)]
            )
            self.assertEqual(result.exit_code, 0, result.output)
            sessions_dir = root / ".trevvos" / "sessions"
            reports = list(sessions_dir.glob("*/tests_inspect_report.md"))
            self.assertTrue(len(reports) >= 1, "tests_inspect_report.md not found")
            meta_files = list(sessions_dir.glob("*/tests_inspect_metadata.json"))
            self.assertTrue(len(meta_files) >= 1)
            meta = json.loads(meta_files[0].read_text())
            self.assertIn("source_path", meta)

    def test_tests_inspect_json_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            result = runner.invoke(
                app, ["tests", "inspect", "calculator.py", "--json", "--path", str(root)]
            )
            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output.strip())
            self.assertIn("status", payload)
            self.assertIn("symbols_missing", payload)

    def test_tests_inspect_nonexistent_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            result = runner.invoke(
                app, ["tests", "inspect", "does_not_exist.py", "--path", str(root)]
            )
            self.assertNotEqual(result.exit_code, 0)


class TestsAddSmokeTests(unittest.TestCase):
    def test_tests_add_symbol_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(result.status, "test_diff_validated")
            self.assertTrue(result.write_allowed)
            self.assertFalse(result.applied)
            session_path = result.session_path
            self.assertTrue((session_path / "test_diff.patch").exists())
            sandbox = json.loads((session_path / "test_sandbox_results.json").read_text())
            self.assertEqual(sandbox["status"], "passed")
            meta = json.loads((session_path / "test_generation_metadata.json").read_text())
            self.assertTrue(meta["write_allowed"])
            # Working tree is NOT modified in dry-run
            self.assertFalse((root / "tests" / "test_calculator.py").exists())

    def test_tests_add_all_symbols_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            result = run_tests_add_workflow(
                _make_add_request(root, symbol=None, all_symbols=True), provider
            )
            self.assertEqual(result.status, "test_diff_validated")
            self.assertTrue(result.write_allowed)
            self.assertEqual(provider.call_count, 1)

    def test_tests_add_nonexistent_symbol_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            with self.assertRaises(WorkspaceError):
                run_tests_add_workflow(
                    _make_add_request(root, symbol="does_not_exist"), provider
                )
            self.assertEqual(provider.call_count, 0)

    def test_tests_add_existing_tests_skips_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo_with_tests(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            result = run_tests_add_workflow(
                _make_add_request(root, symbol="divide"), provider
            )
            self.assertEqual(result.status, "skipped_existing_tests")
            self.assertEqual(provider.call_count, 0)

    def test_tests_add_provider_called_once_on_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(result.status, "test_diff_validated")
            self.assertEqual(provider.call_count, 1)


class TestsApplySmokeTests(unittest.TestCase):
    def test_tests_apply_session_applies_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            add_result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(add_result.status, "test_diff_validated")

            apply_result = run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=add_result.session_id)
            )
            self.assertEqual(apply_result.status, "applied")
            self.assertEqual(apply_result.exit_code, 0)
            self.assertTrue((root / "tests" / "test_calculator.py").exists())
            apply_json = json.loads(
                (apply_result.session_path / "test_apply_result.json").read_text()
            )
            self.assertTrue(apply_json["applied"])
            self.assertFalse(apply_json["already_applied"])
            self.assertEqual(apply_json["reason"], "applied")

    def test_tests_apply_already_applied_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            add_result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(add_result.status, "test_diff_validated")

            # Apply manually
            patch_path = add_result.session_path / "test_diff.patch"
            subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=root, check=True, capture_output=True,
            )

            # Now apply via workflow — should detect already applied
            apply_result = run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=add_result.session_id)
            )
            self.assertEqual(apply_result.status, "already_applied")
            self.assertTrue(apply_result.already_applied)
            self.assertEqual(apply_result.exit_code, 0)
            apply_json = json.loads(
                (apply_result.session_path / "test_apply_result.json").read_text()
            )
            self.assertTrue(apply_json["already_applied"])
            self.assertEqual(apply_json["reason"], "reverse_check_passed")

    def test_tests_apply_latest_finds_applicable_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            add_result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(add_result.status, "test_diff_validated")

            session, reason = find_best_tests_apply_session(root)
            self.assertIsNotNone(session)
            self.assertEqual(reason, "applicable")
            self.assertEqual(session.metadata.id, add_result.session_id)

    def test_tests_apply_without_validated_session_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            # No sessions at all — CLI should exit non-zero
            result = runner.invoke(app, ["tests", "apply", "--yes", "--path", str(root)])
            self.assertNotEqual(result.exit_code, 0)

    def test_tests_apply_help_works(self) -> None:
        result = runner.invoke(app, ["tests", "apply", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--session", result.output)
        self.assertIn("--latest", result.output)


class EndToEndSmokeTests(unittest.TestCase):
    def test_add_then_apply_then_unittest(self) -> None:
        """Full pipeline: dry-run → apply → unittest passes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())

            add_result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(add_result.status, "test_diff_validated")

            apply_result = run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=add_result.session_id)
            )
            self.assertEqual(apply_result.status, "applied")
            self.assertEqual(apply_result.exit_code, 0)
            self.assertTrue((root / "tests" / "test_calculator.py").exists())

            proc = subprocess.run(
                ["python", "-m", "unittest", "discover", "-s", "tests"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_apply_does_not_call_provider(self) -> None:
        """tests apply must never call the LLM provider."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())

            add_result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(add_result.status, "test_diff_validated")
            calls_before = provider.call_count

            run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=add_result.session_id)
            )
            self.assertEqual(provider.call_count, calls_before)


class ControlledTestingTimingTests(unittest.TestCase):
    """Verify duration fields appear in controlled testing command outputs."""

    def test_tests_inspect_output_contains_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            result = runner.invoke(
                app, ["tests", "inspect", "calculator.py", "--path", str(root)]
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Duration:", result.output)

    def test_tests_inspect_metadata_contains_duration_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            runner.invoke(app, ["tests", "inspect", "calculator.py", "--path", str(root)])
            sessions_dir = root / ".trevvos" / "sessions"
            meta_files = list(sessions_dir.glob("*/tests_inspect_metadata.json"))
            self.assertTrue(len(meta_files) >= 1)
            meta = json.loads(meta_files[0].read_text())
            self.assertIn("duration_seconds", meta)
            self.assertIsInstance(meta["duration_seconds"], (int, float))

    def test_tests_inspect_json_output_has_no_plain_duration_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            result = runner.invoke(
                app, ["tests", "inspect", "calculator.py", "--json", "--path", str(root)]
            )
            self.assertEqual(result.exit_code, 0, result.output)
            # Must be valid JSON (no stray "Duration:" line)
            json.loads(result.output.strip())

    def test_tests_apply_human_output_contains_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            add_result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(add_result.status, "test_diff_validated")
            result = runner.invoke(
                app,
                ["tests", "apply", "--yes", "--session", add_result.session_id, "--path", str(root)],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Duration:", result.output)

    def test_tests_apply_json_contains_duration_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            add_result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(add_result.status, "test_diff_validated")
            result = runner.invoke(
                app,
                [
                    "tests", "apply", "--yes", "--json",
                    "--session", add_result.session_id,
                    "--path", str(root),
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn('"duration_seconds"', result.output)

    def test_tests_apply_json_has_no_plain_duration_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_divide_test_response())
            add_result = run_tests_add_workflow(_make_add_request(root), provider)
            self.assertEqual(add_result.status, "test_diff_validated")
            result = runner.invoke(
                app,
                [
                    "tests", "apply", "--yes", "--json",
                    "--session", add_result.session_id,
                    "--path", str(root),
                ],
            )
            self.assertEqual(result.exit_code, 0)
            self.assertNotIn("\nDuration:", result.output)

    def test_tests_add_output_contains_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            with patch("trevvos_forge.cli.build_provider") as mock_bp:
                mock_bp.return_value.generate.return_value = _create_divide_test_response()
                result = runner.invoke(
                    app,
                    ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)],
                )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Duration:", result.output)


if __name__ == "__main__":
    unittest.main()
