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
                    max_generation_retries=1,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
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
                    max_generation_retries=1,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
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
                    max_generation_retries=1,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
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
                    max_generation_retries=1,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
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
                    max_generation_retries=1,
                    max_structure_retries=0,
                    max_sandbox_retries=0,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "failed_sandbox_after_retries")
            self.assertFalse(result.write_allowed)
            self.assertFalse(result.applied)
            self.assertTrue((result.session_path / "test_sandbox_results.json").exists())
            self.assertFalse((result.session_path / "test_apply_result.json").exists())

    def test_sandbox_retry_recovers_from_bad_expectation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo_with_power(Path(temporary_directory))
            provider = _FakeProvider([
                _create_power_bad_expectation_response(),
                _create_power_good_response(),
            ])

            result = run_tests_add_workflow(
                TestAddRequest(
                    repo_root=root,
                    source_path="calculator.py",
                    symbol="power",
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
            self.assertEqual(provider.call_count, 2)
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            summary = (result.session_path / "test_generation_summary.md").read_text(encoding="utf-8")
            prompt = (result.session_path / "test_generation_sandbox_retry_prompt.md").read_text(encoding="utf-8")
            patch_text = (result.session_path / "test_diff.patch").read_text(encoding="utf-8")

            self.assertEqual(metadata["sandbox_retries"]["max"], 1)
            self.assertEqual(metadata["sandbox_retries"]["used"], 1)
            self.assertEqual(metadata["sandbox_retries"]["status"], "succeeded_after_retry")
            self.assertIn("AssertionError: ValueError not raised", prompt)
            self.assertIn("Do not assert exceptions unless the source implementation clearly raises them.", prompt)
            self.assertIn("## Sandbox retry", summary)
            self.assertIn("Result: succeeded_after_retry", summary)
            self.assertNotIn("assertRaises(ValueError)", patch_text)

    def test_sandbox_retry_zero_disables_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo_with_power(Path(temporary_directory))
            provider = _FakeProvider(_create_power_bad_expectation_response())

            result = run_tests_add_workflow(
                TestAddRequest(
                    repo_root=root,
                    source_path="calculator.py",
                    symbol="power",
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
                    max_sandbox_retries=0,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "failed_sandbox_after_retries")
            self.assertEqual(provider.call_count, 1)
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            self.assertEqual(metadata["sandbox_retries"]["max"], 0)
            self.assertEqual(metadata["sandbox_retries"]["used"], 0)
            self.assertEqual(metadata["sandbox_retries"]["status"], "failed_after_retries")

    def test_sandbox_retry_fails_after_exhausting_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo_with_power(Path(temporary_directory))
            provider = _FakeProvider([
                _create_power_bad_expectation_response(),
                _create_power_bad_expectation_response(),
            ])

            result = run_tests_add_workflow(
                TestAddRequest(
                    repo_root=root,
                    source_path="calculator.py",
                    symbol="power",
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

            self.assertEqual(result.status, "failed_sandbox_after_retries")
            self.assertEqual(provider.call_count, 2)
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            self.assertEqual(metadata["sandbox_retries"]["max"], 1)
            self.assertEqual(metadata["sandbox_retries"]["used"], 1)
            self.assertEqual(metadata["sandbox_retries"]["status"], "failed_after_retries")
            self.assertTrue((result.session_path / "test_generation_sandbox_retry_prompt.md").exists())

    def test_schema_retry_recovers_from_unknown_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider([
                _create_unknown_operation_response("insert_at_position"),
                _create_test_file_response(),
            ])

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
            self.assertEqual(provider.call_count, 2)
            self.assertTrue((result.session_path / "test_generation_error.json").exists())
            self.assertTrue((result.session_path / "test_generation_schema_retry_prompt.md").exists())
            self.assertTrue((result.session_path / "test_generation_schema_retry_raw_response.json").exists())
            self.assertTrue((result.session_path / "test_generation_schema_retry_metadata.json").exists())
            error = _read_json(result.session_path / "test_generation_error.json")
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            summary = (result.session_path / "test_generation_summary.md").read_text(encoding="utf-8")

            self.assertEqual(error["error_type"], "unknown_operation")
            self.assertEqual(error["operation"], "insert_at_position")
            self.assertEqual(metadata["generation_retries"]["max"], 1)
            self.assertEqual(metadata["generation_retries"]["used"], 1)
            self.assertEqual(metadata["generation_retries"]["status"], "succeeded_after_retry")
            self.assertIn("## Test generation schema retry", summary)
            self.assertIn("Result: succeeded_after_retry", summary)

    def test_schema_retry_zero_disables_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_unknown_operation_response("insert_at_position"))

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
                    max_generation_retries=0,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "failed_test_generation_schema")
            self.assertEqual(provider.call_count, 1)
            self.assertFalse((result.session_path / "test_diff.patch").exists())
            self.assertFalse((result.session_path / "test_sandbox_results.json").exists())
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            self.assertEqual(metadata["generation_retries"]["max"], 0)
            self.assertEqual(metadata["generation_retries"]["used"], 0)
            self.assertEqual(metadata["generation_retries"]["status"], "failed_after_retries")

    def test_schema_retry_fails_after_exhausting_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_unknown_operation_response("insert_at_position"))

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

            self.assertEqual(result.status, "failed_test_generation_schema")
            self.assertEqual(provider.call_count, 2)
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            self.assertEqual(metadata["generation_retries"]["max"], 1)
            self.assertEqual(metadata["generation_retries"]["used"], 1)
            self.assertEqual(metadata["generation_retries"]["status"], "failed_after_retries")
            self.assertTrue((result.session_path / "test_generation_schema_retry_prompt.md").exists())

    def test_schema_retry_prompt_contains_error_and_allowed_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider([
                _create_unknown_operation_response(),
                _create_test_file_response(),
            ])

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
            prompt = (result.session_path / "test_generation_schema_retry_prompt.md").read_text(encoding="utf-8")
            self.assertIn("replace_in_file is not a valid operation", prompt)
            self.assertIn("insert_at_position", prompt)
            self.assertIn("replace_exact_text", prompt)
            self.assertIn("replace_block", prompt)
            self.assertIn("append_to_file", prompt)
            self.assertIn("create_file", prompt)
            self.assertIn("Return only valid JSON", prompt)

    def test_unknown_operation_classification_handles_multiple_operations(self) -> None:
        for operation in ["replace_in_file", "insert_at_position", "insert_after_block"]:
            with self.subTest(operation=operation):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = _sample_repo(Path(temporary_directory))
                    provider = _FakeProvider(_create_unknown_operation_response(operation))

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
                            max_generation_retries=0,
                            max_structure_retries=1,
                            max_sandbox_retries=1,
                            timeout=120,
                        ),
                        provider,
                    )

                    self.assertEqual(result.status, "failed_test_generation_schema")
                    error = _read_json(result.session_path / "test_generation_error.json")
                    self.assertEqual(error["error_type"], "unknown_operation")
                    self.assertEqual(error["operation"], operation)

    def test_schema_retry_does_not_run_for_guardrail_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_production_file_change_response())

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

            self.assertEqual(result.status, "failed_test_generation_guardrail")
            self.assertEqual(provider.call_count, 1)
            self.assertFalse((result.session_path / "test_generation_schema_retry_prompt.md").exists())
            self.assertEqual(result.metadata["status"], "failed_test_generation_guardrail")

    def test_schema_retry_does_not_run_for_structure_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_structure_retry_bad_response())

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
                    max_generation_retries=1,
                    max_structure_retries=0,
                    max_sandbox_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "tests_add_failed")
            self.assertEqual(provider.call_count, 1)
            self.assertTrue((result.session_path / "test_structure_validation.json").exists())
            self.assertFalse((result.session_path / "test_generation_schema_retry_prompt.md").exists())

    def test_schema_retry_write_applies_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider([
                _create_unknown_operation_response("insert_at_position"),
                _create_test_file_response(),
            ])

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
                    max_generation_retries=1,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "tests_applied")
            self.assertTrue((root / "tests" / "test_calculator.py").exists())
            self.assertTrue((result.session_path / "test_apply_result.json").exists())

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


def _sample_repo_with_power(root: Path) -> Path:
    root = _sample_repo(root)
    content = (root / "calculator.py").read_text(encoding="utf-8")
    (root / "calculator.py").write_text(
        content + "\n\ndef power(base, exponent):\n    return base ** exponent\n",
        encoding="utf-8",
    )
    _git(root, ["add", "calculator.py"])
    _git(root, ["commit", "-m", "add power"])
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


def _create_power_bad_expectation_response() -> str:
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
                        "from calculator import power\n\n\n"
                        "class TestCalculator(unittest.TestCase):\n"
                        "    def test_power(self):\n"
                        "        self.assertEqual(power(2, 3), 8)\n"
                        "        self.assertEqual(power(5, 0), 1)\n"
                        "        with self.assertRaises(ValueError):\n"
                        "            power(-2, 0.5)\n"
                    ),
                }
            ]
        }
    )


def _create_power_good_response() -> str:
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
                        "from calculator import power\n\n\n"
                        "class TestCalculator(unittest.TestCase):\n"
                        "    def test_power(self):\n"
                        "        self.assertEqual(power(2, 3), 8)\n"
                        "        self.assertEqual(power(5, 0), 1)\n"
                        "        self.assertEqual(power(4, 0.5), 2.0)\n"
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


def _create_unknown_operation_response(operation: str = "replace_in_file") -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "created",
                    "mode": "operation_based_edit",
                    "operation": operation,
                    "content": "irrelevant",
                }
            ]
        }
    )


def _create_production_file_change_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "calculator.py",
                    "change_type": "modified",
                    "mode": "operation_based_edit",
                    "operation": "append_to_file",
                    "insert": "\n# bad\n",
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


