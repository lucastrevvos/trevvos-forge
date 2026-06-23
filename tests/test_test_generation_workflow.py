import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.test_generation_workflow import TestAddRequest, run_tests_add_workflow


class TestGenerationWorkflowTests(unittest.TestCase):
    def test_happy_path_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
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
                    max_structure_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "test_diff_validated")
            self.assertFalse(result.applied)
            self.assertTrue(result.write_allowed)
            self.assertTrue((result.session_path / "test_generation_metadata.json").exists())
            self.assertTrue((result.session_path / "test_diff.patch").exists())
            self.assertTrue((result.session_path / "test_sandbox_results.json").exists())
            self.assertEqual(provider.call_count, 1)

    def test_existing_tests_skip_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import divide\n\n"
                "class TestCalculator(unittest.TestCase):\n"
                "    def test_divide_by_zero(self):\n"
                "        divide(1, 1)\n",
                encoding="utf-8",
            )
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
                    max_structure_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "skipped_existing_tests")
            self.assertEqual(provider.call_count, 0)
            self.assertTrue((result.session_path / "existing_tests_check.json").exists())
            self.assertFalse((result.session_path / "test_diff.patch").exists())

    def test_import_repair_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_missing_imports_repairable_response())

            result = run_tests_add_workflow(
                TestAddRequest(
                    repo_root=root,
                    source_path="calculator.py",
                    symbol=None,
                    all_symbols=True,
                    test_file=None,
                    unit=False,
                    e2e=False,
                    write=False,
                    yes=False,
                    force=False,
                    keep_sandbox=False,
                    max_structure_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "test_diff_validated")
            repair = _read_json(result.session_path / "test_import_repair.json")
            self.assertEqual(repair["status"], "repaired")
            self.assertIn("test_import_repair.json", result.artifacts["import_repair"])

    def test_structure_retry_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider([_create_structure_retry_bad_response(), _create_structure_retry_good_response()])

            result = run_tests_add_workflow(
                TestAddRequest(
                    repo_root=root,
                    source_path="calculator.py",
                    symbol=None,
                    all_symbols=True,
                    test_file=None,
                    unit=False,
                    e2e=False,
                    write=False,
                    yes=False,
                    force=False,
                    keep_sandbox=False,
                    max_structure_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "test_diff_validated")
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            self.assertEqual(metadata["structure_retries"]["status"], "succeeded_after_retry")
            self.assertEqual(provider.call_count, 2)
            self.assertTrue((result.session_path / "test_generation_retry_prompt.md").exists())

    def test_write_blocked_when_sandbox_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_failing_test_file_response())

            result = run_tests_add_workflow(
                TestAddRequest(
                    repo_root=root,
                    source_path="calculator.py",
                    symbol="divide",
                    all_symbols=False,
                    test_file=None,
                    unit=False,
                    e2e=False,
                    write=True,
                    yes=True,
                    force=False,
                    keep_sandbox=False,
                    max_structure_retries=0,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "write_blocked")
            self.assertFalse(result.write_allowed)
            self.assertFalse(result.applied)
            self.assertTrue((result.session_path / "test_sandbox_results.json").exists())
            self.assertFalse((result.session_path / "test_apply_result.json").exists())

    def test_cli_delegates_to_workflow(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            with patch("trevvos_forge.cli.run_tests_add_workflow") as run_workflow:
                run_workflow.return_value = _fake_result(root)
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            run_workflow.assert_called_once()


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


def _create_missing_imports_repairable_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "created",
                    "mode": "operation_based_edit",
                    "operation": "create_file",
                    "content": (
                        "import unittest\n"
                        "from calculator import divide\n\n"
                        "class TestCalculator(unittest.TestCase):\n"
                        "    def test_divide_by_zero_raises_value_error(self):\n"
                        "        with self.assertRaises(ValueError):\n"
                        "            divide(10, 0)\n\n"
                        "    def test_addition(self):\n"
                        "        self.assertEqual(add(2, 3), 5)\n\n"
                        "    def test_subtraction(self):\n"
                        "        self.assertEqual(subtract(5, 2), 3)\n"
                    ),
                }
            ]
        }
    )


def _create_structure_retry_bad_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "created",
                    "mode": "operation_based_edit",
                    "operation": "create_file",
                    "content": (
                        "import unittest\n"
                        "from calculator import divide\n\n"
                        "class TestCalculator(unittest.TestCase):\n"
                        "    def test_divide_by_zero(self):\n"
                        "        divide(1, 1)\n\n"
                        "def test_add_positive_numbers():\n"
                        "    self.assertEqual(add(1, 2), 3)\n"
                    ),
                }
            ]
        }
    )


def _create_structure_retry_good_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "created",
                    "mode": "operation_based_edit",
                    "operation": "create_file",
                    "content": (
                        "import unittest\n"
                        "from calculator import add, divide, multiply, subtract\n\n\n"
                        "class TestCalculator(unittest.TestCase):\n"
                        "    def test_add(self):\n"
                        "        self.assertEqual(add(2, 3), 5)\n\n"
                        "    def test_subtract(self):\n"
                        "        self.assertEqual(subtract(5, 3), 2)\n\n"
                        "    def test_multiply(self):\n"
                        "        self.assertEqual(multiply(2, 3), 6)\n\n"
                        "    def test_divide(self):\n"
                        "        self.assertEqual(divide(6, 3), 2)\n"
                    ),
                }
            ]
        }
    )


def _create_failing_test_file_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "created",
                    "mode": "operation_based_edit",
                    "operation": "create_file",
                    "content": (
                        "import unittest\n\n\n"
                        "class TestGeneratedFailure(unittest.TestCase):\n"
                        "    def test_failure(self):\n"
                        "        self.assertEqual(1, 2)\n"
                    ),
                }
            ]
        }
    )


def _fake_result(root: Path):
    session_dir = root / ".trevvos" / "sessions" / "fake-session"
    session_dir.mkdir(parents=True, exist_ok=True)
    return type(
        "Result",
        (),
        {
            "status": "test_diff_validated",
            "session_id": "fake-session",
            "session_path": session_dir,
            "source_path": "calculator.py",
            "test_file": "tests/test_calculator.py",
            "symbols": ["divide"],
            "files_changed": ["tests/test_calculator.py"],
            "write_allowed": True,
            "applied": False,
            "artifacts": {"existing_tests_check": "existing_tests_check.json", "metadata": "test_generation_metadata.json"},
            "message": "[green]Test patch generated and validated in sandbox.[/green]",
            "exit_code": 0,
            "metadata": {"status": "diff_ready"},
            "prompt_ref": "test_generation@1.0.0",
            "next_command": "python -m unittest discover -s tests",
            "test_commands": ["python -m unittest tests.test_calculator"],
            "command_source": "targeted",
            "symbol_selector": {"enabled": False, "reason": "framework_not_supported"},
            "sandbox_status": "passed",
        },
    )()


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


if __name__ == "__main__":
    unittest.main()
