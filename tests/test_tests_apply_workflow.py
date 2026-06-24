import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.test_apply_workflow import (
    TestApplyRequest,
    find_best_tests_apply_session,
    run_tests_apply_workflow,
)
from trevvos_forge.test_generation_workflow import TestAddRequest, run_tests_add_workflow


class TestsApplyWorkflowTests(unittest.TestCase):
    def test_apply_applies_validated_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )

            self.assertEqual(add_result.status, "test_diff_validated")
            self.assertTrue(add_result.write_allowed)

            result = run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=add_result.session_id)
            )

            self.assertEqual(result.status, "applied")
            self.assertTrue(result.applied)
            self.assertEqual(result.exit_code, 0)
            self.assertTrue((root / "tests" / "test_calculator.py").exists())
            self.assertTrue((result.session_path / "test_apply_result.json").exists())
            apply_data = json.loads(
                (result.session_path / "test_apply_result.json").read_text(encoding="utf-8")
            )
            self.assertTrue(apply_data["applied"])
            self.assertEqual(apply_data["session"], add_result.session_id)

    def test_apply_uses_current_session_when_no_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )

            self.assertEqual(add_result.status, "test_diff_validated")

            result = run_tests_apply_workflow(TestApplyRequest(repo_root=root, session_id=None))

            self.assertEqual(result.status, "applied")
            self.assertEqual(result.session_id, add_result.session_id)
            self.assertTrue((root / "tests" / "test_calculator.py").exists())

    def test_apply_blocks_when_sandbox_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            session_id, session_path = _make_minimal_session(root)
            (session_path / "test_diff.patch").write_text("--- a\n+++ b\n", encoding="utf-8")
            (session_path / "test_sandbox_results.json").write_text(
                json.dumps({"status": "failed"}), encoding="utf-8"
            )

            result = run_tests_apply_workflow(TestApplyRequest(repo_root=root, session_id=session_id))

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.block_reason, "sandbox_not_passed")
            self.assertFalse(result.applied)
            self.assertEqual(result.exit_code, 1)

    def test_apply_blocks_when_patch_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            session_id, session_path = _make_minimal_session(root)
            # test_diff.patch is not written

            result = run_tests_apply_workflow(TestApplyRequest(repo_root=root, session_id=session_id))

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.block_reason, "no_patch")
            self.assertFalse(result.applied)

    def test_apply_blocks_when_git_apply_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )

            self.assertEqual(add_result.status, "test_diff_validated")
            tests_dir = root / "tests"
            tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_calculator.py").write_text(
                "# conflicting content\n", encoding="utf-8"
            )
            _git(root, ["add", "tests/"])
            _git(root, ["commit", "-m", "add conflicting test file"])

            result = run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=add_result.session_id)
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.block_reason, "check_failed")
            self.assertFalse(result.applied)
            self.assertTrue((result.session_path / "test_apply_result.json").exists())
            apply_data = json.loads(
                (result.session_path / "test_apply_result.json").read_text(encoding="utf-8")
            )
            self.assertFalse(apply_data["applied"])

    def test_apply_does_not_call_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )

            self.assertEqual(add_result.status, "test_diff_validated")
            calls_before = provider.call_count

            result = run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=add_result.session_id)
            )

            self.assertEqual(result.status, "applied")
            self.assertEqual(provider.call_count, calls_before)

    def test_next_message_changed_after_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )

            self.assertEqual(result.status, "test_diff_validated")
            self.assertEqual(result.sandbox_status, "passed")

            from trevvos_forge.test_generation_workflow import render_test_add_result

            printed: list[str] = []

            class _FakeConsole:
                def print(self, msg: str = "", **_kwargs: object) -> None:
                    printed.append(str(msg))

            render_test_add_result(result=result, json_output=False, console=_FakeConsole())

            combined = "\n".join(printed)
            self.assertIn("trevvos tests apply", combined)
            self.assertNotIn("--write", combined)

    def test_apply_help_works(self) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["tests", "apply", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("apply", result.output.lower())

    def test_apply_blocks_non_test_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            session_id, session_path = _make_minimal_session(root)

            patch_text = _make_patch_text("calculator.py", "# added by test\n")
            (session_path / "test_diff.patch").write_text(patch_text, encoding="utf-8")

            (session_path / "test_sandbox_results.json").write_text(
                json.dumps({"status": "passed"}), encoding="utf-8"
            )
            (session_path / "test_generation_metadata.json").write_text(
                json.dumps({"write_allowed": True}), encoding="utf-8"
            )
            (session_path / "test_structure_validation.json").write_text(
                json.dumps({"status": "passed"}), encoding="utf-8"
            )
            (session_path / "test_file_changes.json").write_text(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "calculator.py",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "append_to_file",
                                "insert": "# added by test\n",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = run_tests_apply_workflow(TestApplyRequest(repo_root=root, session_id=session_id))

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.block_reason, "guardrail_failed")
            self.assertFalse(result.applied)


    def test_apply_with_explicit_session_ignores_current_session(self) -> None:
        """--session <id> applies that session even if current session is a failed one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            # Session A: validated
            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )
            self.assertEqual(add_result.status, "test_diff_validated")
            validated_session_id = add_result.session_id

            # Session B: minimal failed session becomes current
            failed_session_id, _ = _make_minimal_session(root)  # writes current_session file
            self.assertNotEqual(failed_session_id, validated_session_id)

            # Apply explicit session A — must succeed despite current being B
            result = run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=validated_session_id)
            )

            self.assertEqual(result.status, "applied")
            self.assertEqual(result.session_id, validated_session_id)
            self.assertTrue((root / "tests" / "test_calculator.py").exists())

    def test_apply_without_session_suggests_latest_validated(self) -> None:
        """tests apply without --session suggests latest validated session when current is blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            # Session A: validated (created first, will have an earlier session ID)
            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )
            self.assertEqual(add_result.status, "test_diff_validated")
            validated_session_id = add_result.session_id

            # Session B: minimal failed session — becomes current
            _make_minimal_session(root)

            # Apply without --session: current session B is blocked
            result = run_tests_apply_workflow(TestApplyRequest(repo_root=root, session_id=None))

            self.assertEqual(result.status, "blocked")
            self.assertIsNotNone(result.suggestion, "Suggestion must be provided when validated session exists")
            self.assertIn(validated_session_id, result.suggestion)
            self.assertIn("trevvos tests apply --session", result.suggestion)

    def test_apply_without_session_no_validated_session(self) -> None:
        """tests apply without --session shows helpful hint when no validated sessions exist."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            _make_minimal_session(root)  # current session: failed, no patch

            result = run_tests_apply_workflow(TestApplyRequest(repo_root=root, session_id=None))

            self.assertEqual(result.status, "blocked")
            self.assertIsNotNone(result.suggestion)
            self.assertIn("tests add", result.suggestion)


def _make_minimal_session(root: Path) -> tuple[str, Path]:
    session_id = "apply-test-session"
    session_path = root / ".trevvos" / "sessions" / session_id
    session_path.mkdir(parents=True)
    (session_path / "metadata.json").write_text(
        json.dumps(
            {
                "id": session_id,
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "test_diff_validated",
                "command": "tests add",
                "workspace_root": str(root),
            }
        ),
        encoding="utf-8",
    )
    (root / ".trevvos" / "current_session").write_text(session_id, encoding="utf-8")
    return session_id, session_path


def _make_patch_text(file_path: str, content_to_add: str) -> str:
    return (
        f"diff --git a/{file_path} b/{file_path}\n"
        f"--- a/{file_path}\n"
        f"+++ b/{file_path}\n"
        f"@@ -1 +1,2 @@\n"
        f" existing line\n"
        f"+{content_to_add}"
    )


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
        "        raise ValueError('division by zero')\n"
        "    return a / b\n",
        encoding="utf-8",
    )
    _git(root, ["add", "calculator.py"])
    _git(root, ["commit", "-m", "initial"])
    return root


def _create_test_file_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
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
                    ),
                }
            ]
        }
    )


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class _FakeProvider:
    def __init__(self, response: str | list[str]) -> None:
        self.responses = [response] if isinstance(response, str) else list(response)
        if not self.responses:
            raise ValueError("response must not be empty")
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


class AlreadyAppliedTests(unittest.TestCase):
    def test_apply_session_detects_already_applied(self) -> None:
        """When the patch is already in the working tree, status is already_applied with exit_code 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )
            self.assertEqual(add_result.status, "test_diff_validated")
            session_id = add_result.session_id
            session_path = root / ".trevvos" / "sessions" / session_id

            # Manually apply the patch to simulate it already being applied
            _git(root, ["apply", str(session_path / "test_diff.patch")])

            result = run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=session_id)
            )

            self.assertEqual(result.status, "already_applied")
            self.assertTrue(result.already_applied)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.reason, "reverse_check_passed")
            apply_data = json.loads(
                (session_path / "test_apply_result.json").read_text(encoding="utf-8")
            )
            self.assertTrue(apply_data["already_applied"])
            self.assertEqual(apply_data["reason"], "reverse_check_passed")

    def test_latest_detects_already_applied(self) -> None:
        """find_best_tests_apply_session returns 'already_applied' when patch is in working tree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )
            self.assertEqual(add_result.status, "test_diff_validated")
            session_path = root / ".trevvos" / "sessions" / add_result.session_id

            # Apply the patch manually
            _git(root, ["apply", str(session_path / "test_diff.patch")])

            session, reason = find_best_tests_apply_session(root)
            self.assertIsNotNone(session)
            self.assertEqual(reason, "already_applied")
            self.assertEqual(session.metadata.id, add_result.session_id)

    def test_latest_skips_obsolete_picks_next(self) -> None:
        """find_best_tests_apply_session skips a session with unapplicable patch and picks the next."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            # Session B (earlier, real, applicable): run dry-run
            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )
            self.assertEqual(add_result.status, "test_diff_validated")
            real_session_id = add_result.session_id

            # Session A (alphabetically later = newer via reverse sort, bad patch)
            _make_validated_session_with_bad_patch(root, "zzz-obsolete-session")

            session, reason = find_best_tests_apply_session(root)
            self.assertIsNotNone(session)
            self.assertEqual(session.metadata.id, real_session_id)
            self.assertEqual(reason, "applicable")

    def test_latest_no_applicable_session(self) -> None:
        """find_best_tests_apply_session returns (None, 'none') when no session's patch applies."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )
            self.assertEqual(add_result.status, "test_diff_validated")

            # Create tests/test_calculator.py with DIFFERENT content → makes patch unapplicable in both directions
            tests_dir = root / "tests"
            tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_calculator.py").write_text(
                "# completely different content\nprint('hello')\n",
                encoding="utf-8",
            )
            _git(root, ["add", "tests/"])
            _git(root, ["commit", "-m", "add conflicting test file"])

            session, reason = find_best_tests_apply_session(root)
            self.assertIsNone(session)
            self.assertEqual(reason, "none")

    def test_apply_result_json_has_new_fields(self) -> None:
        """test_apply_result.json includes already_applied and reason fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )
            self.assertEqual(add_result.status, "test_diff_validated")
            session_id = add_result.session_id
            session_path = root / ".trevvos" / "sessions" / session_id

            # Apply the patch, then call workflow (already_applied path)
            _git(root, ["apply", str(session_path / "test_diff.patch")])
            run_tests_apply_workflow(TestApplyRequest(repo_root=root, session_id=session_id))

            apply_data = json.loads(
                (session_path / "test_apply_result.json").read_text(encoding="utf-8")
            )
            self.assertIn("already_applied", apply_data)
            self.assertIn("reason", apply_data)
            self.assertTrue(apply_data["already_applied"])
            self.assertEqual(apply_data["reason"], "reverse_check_passed")

    def test_apply_check_failed_not_already_applied(self) -> None:
        """When both forward and reverse check fail, status is blocked with check_failed and correct JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(_create_test_file_response())

            add_result = run_tests_add_workflow(
                TestAddRequest(
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
                ),
                provider,
            )
            self.assertEqual(add_result.status, "test_diff_validated")
            session_id = add_result.session_id

            # Create tests/test_calculator.py with different content → both checks fail
            tests_dir = root / "tests"
            tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_calculator.py").write_text(
                "# different content, not matching patch\n",
                encoding="utf-8",
            )
            _git(root, ["add", "tests/"])
            _git(root, ["commit", "-m", "add conflicting file"])

            result = run_tests_apply_workflow(
                TestApplyRequest(repo_root=root, session_id=session_id)
            )

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.block_reason, "check_failed")
            self.assertEqual(result.exit_code, 1)
            apply_data = json.loads(
                (result.session_path / "test_apply_result.json").read_text(encoding="utf-8")
            )
            self.assertFalse(apply_data["applied"])
            self.assertFalse(apply_data["already_applied"])
            self.assertEqual(apply_data["reason"], "check_failed")
            self.assertEqual(apply_data["reverse_check"], "failed")


def _make_validated_session_with_bad_patch(root: Path, session_id: str) -> tuple[str, Path]:
    """Create a fake validated session whose patch will fail both forward and reverse git apply --check."""
    session_path = root / ".trevvos" / "sessions" / session_id
    session_path.mkdir(parents=True)
    (session_path / "metadata.json").write_text(
        json.dumps(
            {
                "id": session_id,
                "created_at": "2030-01-01T00:00:00+00:00",
                "status": "test_diff_validated",
                "command": "tests add",
                "workspace_root": str(root),
            }
        ),
        encoding="utf-8",
    )
    # A patch targeting content that doesn't exist in the working tree
    (session_path / "test_diff.patch").write_text(
        "diff --git a/tests/test_calculator.py b/tests/test_calculator.py\n"
        "--- a/tests/test_calculator.py\n"
        "+++ b/tests/test_calculator.py\n"
        "@@ -1,2 +1,3 @@\n"
        " this_line_does_not_exist\n"
        " another_nonexistent_line\n"
        "+inserted_line\n",
        encoding="utf-8",
    )
    (session_path / "test_sandbox_results.json").write_text(
        json.dumps({"status": "passed"}), encoding="utf-8"
    )
    (session_path / "test_generation_metadata.json").write_text(
        json.dumps({"write_allowed": True}), encoding="utf-8"
    )
    (session_path / "test_structure_validation.json").write_text(
        json.dumps({"status": "passed"}), encoding="utf-8"
    )
    (session_path / "test_file_changes.json").write_text(
        json.dumps(
            {
                "changes": [
                    {
                        "path": "tests/test_calculator.py",
                        "change_type": "created",
                        "mode": "operation_based_edit",
                        "operation": "create_file",
                        "content": "import unittest\n",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return session_id, session_path


if __name__ == "__main__":
    unittest.main()
