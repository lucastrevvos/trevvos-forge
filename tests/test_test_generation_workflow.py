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

    def test_unittest_method_repair_runs_before_import_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo_with_power_and_sqrt(Path(temporary_directory))
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import add, divide, multiply, sqrt, subtract\n\n\n"
                "class TestCalculator(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            provider = _FakeProvider(
                _create_unittest_append_method_response(
                    insert=(
                        "\n\n        def test_power_negative_exponent(self):\n"
                        "            self.assertAlmostEqual(power(2, -3), 0.125)\n\n"
                        "        def test_power_zero_exponent(self):\n"
                        "            self.assertEqual(power(2, 0), 1)\n"
                        "    def test_power_positive_exponent(self):\n"
                        "        self.assertEqual(power(2, 3), 8)\n"
                    )
                )
            )

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
            self.assertEqual(provider.call_count, 1)
            session_dir = result.session_path
            repair = _read_json(session_dir / "test_unittest_method_repair.json")
            import_repair = _read_json(session_dir / "test_import_repair.json")
            metadata = _read_json(session_dir / "test_generation_metadata.json")
            summary = (session_dir / "test_generation_summary.md").read_text(encoding="utf-8")
            patch_text = (session_dir / "test_diff.patch").read_text(encoding="utf-8")

            self.assertEqual(repair["status"], "repaired")
            self.assertEqual(repair["strategy"], "normalize_unittest_method_indentation")
            self.assertEqual(
                repair["methods_repaired"],
                [
                    "test_power_negative_exponent",
                    "test_power_zero_exponent",
                    "test_power_positive_exponent",
                ],
            )
            self.assertEqual(import_repair["status"], "repaired")
            self.assertEqual(metadata["test_unittest_method_repair"]["status"], "repaired")
            self.assertEqual(metadata["test_import_repair"]["status"], "repaired")
            self.assertIn("## Unittest method repair", summary)
            self.assertIn("Status: repaired", summary)
            self.assertIn("test_power_positive_exponent", summary)
            self.assertIn("    def test_power_negative_exponent(self):", patch_text)
            self.assertIn("from calculator import add, divide, multiply, power, sqrt, subtract", patch_text)

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

    def test_schema_retry_recovers_from_missing_replacement_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(
                [
                    _create_missing_string_field_response(
                        operation="replace_exact_text",
                        field_name="replacement",
                        value_key="absent",
                    ),
                    _create_test_file_response(),
                ]
            )

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
            error = _read_json(result.session_path / "test_generation_error.json")
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            prompt = (result.session_path / "test_generation_schema_retry_prompt.md").read_text(encoding="utf-8")

            self.assertEqual(provider.call_count, 2)
            self.assertEqual(error["error_type"], "invalid_file_change_schema")
            self.assertEqual(error["field"], "changes[0].replacement")
            self.assertIn("replacement", error["suggested_resolution"])
            self.assertEqual(metadata["generation_retries"]["status"], "succeeded_after_retry")
            self.assertIn("replacement", prompt)
            self.assertIn("replace_exact_text", prompt)

    def test_schema_retry_recovers_from_missing_insert_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(
                [
                    _create_missing_string_field_response(
                        operation="append_to_file",
                        field_name="insert",
                        value_key="null",
                    ),
                    _create_test_file_response(),
                ]
            )

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
            error = _read_json(result.session_path / "test_generation_error.json")

            self.assertEqual(error["error_type"], "invalid_file_change_schema")
            self.assertEqual(error["field"], "changes[0].insert")

    def test_schema_retry_recovers_from_missing_target_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(
                [
                    _create_missing_string_field_response(
                        operation="replace_exact_text",
                        field_name="target",
                        value_key="absent",
                        target_value=None,
                    ),
                    _create_test_file_response(),
                ]
            )

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
            error = _read_json(result.session_path / "test_generation_error.json")

            self.assertEqual(error["error_type"], "invalid_file_change_schema")
            self.assertEqual(error["field"], "changes[0].target")

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


def _sample_repo_with_sqrt(root: Path) -> Path:
    root = _sample_repo(root)
    content = (root / "calculator.py").read_text(encoding="utf-8")
    (root / "calculator.py").write_text(
        content
        + "\n\ndef sqrt(value):\n"
        + "    if value < 0:\n"
        + "        raise ValueError('negative value')\n"
        + "    return value ** 0.5\n",
        encoding="utf-8",
    )
    _git(root, ["add", "calculator.py"])
    _git(root, ["commit", "-m", "add sqrt"])
    return root


def _sample_repo_with_power_and_sqrt(root: Path) -> Path:
    root = _sample_repo_with_sqrt(root)
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


def _create_unittest_append_method_response(*, insert: str) -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "modified",
                    "mode": "operation_based_edit",
                    "operation": "append_to_file",
                    "insert": insert,
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


def _create_missing_string_field_response(
    *,
    operation: str,
    field_name: str,
    value_key: str,
    target_value: str | None = "from calculator import add",
) -> str:
    change = {
        "path": "tests/test_calculator.py",
        "change_type": "modified",
        "mode": "operation_based_edit",
        "operation": operation,
    }
    if target_value is not None:
        change["target"] = target_value
    if value_key == "null":
        change[field_name] = None
    elif value_key == "absent":
        pass
    else:
        change[field_name] = value_key

    return json.dumps({"changes": [change]})


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


def _create_replace_block_not_found_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "modified",
                    "mode": "operation_based_edit",
                    "operation": "replace_block",
                    "target": "def test_power(self):\n    self.assertEqual(power(2, 3), 8)\n",
                    "replacement": "def test_power_fixed(self):\n    self.assertEqual(power(2, 3), 8)\n",
                }
            ]
        }
    )


def _create_append_power_test_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "modified",
                    "mode": "operation_based_edit",
                    "operation": "append_to_file",
                    "insert": "\n    def test_power_basic(self):\n        from calculator import power\n        self.assertEqual(power(2, 3), 8)\n",
                }
            ]
        }
    )


def _create_append_divide_test_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "modified",
                    "mode": "operation_based_edit",
                    "operation": "append_to_file",
                    "insert": "\n    def test_divide_two_positives(self):\n        self.assertEqual(divide(10, 2), 5.0)\n",
                }
            ]
        }
    )


class OperationRetryTests(unittest.TestCase):
    def _make_repo_with_test_file(self, root: Path) -> Path:
        root = _sample_repo(root)
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_calculator.py").write_text(
            "import unittest\n"
            "from calculator import divide\n\n\n"
            "class TestCalculator(unittest.TestCase):\n"
            "    def test_divide_by_zero_raises_value_error(self):\n"
            "        with self.assertRaises(ValueError):\n"
            "            divide(10, 0)\n",
            encoding="utf-8",
        )
        return root

    def test_operation_error_triggers_retry_and_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo_with_test_file(Path(tmp))
            provider = _FakeProvider(
                [_create_replace_block_not_found_response(), _create_append_divide_test_response()]
            )

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
                    force=True,
                    keep_sandbox=False,
                    max_generation_retries=1,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertNotEqual(result.status, "failed_test_generation_operation")
            self.assertEqual(provider.call_count, 2)
            self.assertTrue((result.session_path / "test_generation_operation_error.json").exists())
            self.assertTrue((result.session_path / "test_generation_operation_retry_metadata.json").exists())

    def test_operation_retry_prompt_contains_current_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo_with_test_file(Path(tmp))
            provider = _FakeProvider(
                [_create_replace_block_not_found_response(), _create_append_divide_test_response()]
            )

            run_tests_add_workflow(
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
                    force=True,
                    keep_sandbox=False,
                    max_generation_retries=1,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(provider.call_count, 2)
            retry_prompt = provider.prompts[1]
            self.assertIn("REAL FILE", retry_prompt)
            self.assertIn("do not assume", retry_prompt.lower())
            self.assertIn("test_divide_by_zero_raises_value_error", retry_prompt)

    def test_max_generation_retries_zero_disables_operation_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo_with_test_file(Path(tmp))
            provider = _FakeProvider(_create_replace_block_not_found_response())

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
                    force=True,
                    keep_sandbox=False,
                    max_generation_retries=0,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "failed_test_generation_operation")
            self.assertEqual(provider.call_count, 1)
            self.assertTrue((result.session_path / "test_generation_operation_error.json").exists())

    def test_operation_failure_after_all_retries_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo_with_test_file(Path(tmp))
            provider = _FakeProvider(
                [_create_replace_block_not_found_response(), _create_replace_block_not_found_response()]
            )

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
                    force=True,
                    keep_sandbox=False,
                    max_generation_retries=1,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "failed_test_generation_operation")
            self.assertEqual(provider.call_count, 2)
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            self.assertEqual(metadata["operation_retries"]["used"], 1)
            self.assertEqual(metadata["operation_retries"]["status"], "failed_after_retries")

    def test_schema_error_does_not_trigger_operation_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            provider = _FakeProvider(
                [_create_unknown_operation_response(), _create_test_file_response()]
            )

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

            self.assertNotEqual(result.status, "failed_test_generation_operation")
            self.assertFalse((result.session_path / "test_generation_operation_error.json").exists())

    def test_operation_error_artifacts_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo_with_test_file(Path(tmp))
            provider = _FakeProvider(_create_replace_block_not_found_response())

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
                    force=True,
                    keep_sandbox=False,
                    max_generation_retries=0,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertEqual(result.status, "failed_test_generation_operation")
            error_json = _read_json(result.session_path / "test_generation_operation_error.json")
            self.assertIn("operation", error_json)
            self.assertIn("path", error_json)
            self.assertEqual(error_json["operation"], "replace_block")
            self.assertIn("target not found in", error_json["message"])
            self.assertTrue((result.session_path / "test_generation_operation_error.md").exists())

    def test_operation_retry_metadata_recorded_in_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo_with_test_file(Path(tmp))
            provider = _FakeProvider(
                [_create_replace_block_not_found_response(), _create_append_divide_test_response()]
            )

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
                    force=True,
                    keep_sandbox=False,
                    max_generation_retries=1,
                    max_structure_retries=1,
                    max_sandbox_retries=1,
                    timeout=120,
                ),
                provider,
            )

            self.assertNotEqual(result.status, "failed_test_generation_operation")
            metadata = _read_json(result.session_path / "test_generation_metadata.json")
            op_retries = metadata.get("operation_retries", {})
            self.assertEqual(op_retries.get("used"), 1)
            self.assertEqual(op_retries.get("status"), "succeeded_after_retry")

    def test_sandbox_failure_does_not_set_operation_error_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo_with_power(Path(tmp))
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

            self.assertNotEqual(result.status, "failed_test_generation_operation")
            self.assertFalse((result.session_path / "test_generation_operation_error.json").exists())

    def test_prompt_catalog_has_operation_retry_prompt(self) -> None:
        from trevvos_forge.prompt_catalog import get_prompt

        prompt = get_prompt("test_generation_operation_retry")

        self.assertEqual(prompt.name, "test_generation_operation_retry")
        self.assertEqual(prompt.version, "1.0.0")
        self.assertIn("test_generation_operation_retry_context", prompt.template)
        rendered = prompt.render(test_generation_operation_retry_context="TEST CONTEXT")
        self.assertIn("TEST CONTEXT", rendered)
        self.assertIn("not found", rendered.lower())


class MissingReplacementTests(unittest.TestCase):
    """Tests that missing 'replacement' field in replace_exact_text triggers schema retry, not a raw crash."""

    def _make_request(self, root: Path, *, max_generation_retries: int = 1) -> "TestAddRequest":
        return TestAddRequest(
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
            max_generation_retries=max_generation_retries,
            max_structure_retries=1,
            max_sandbox_retries=1,
            timeout=120,
        )

    def test_missing_replacement_triggers_schema_retry(self) -> None:
        """replace_exact_text with 'insert' instead of 'replacement' triggers schema retry."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            bad = _create_missing_string_field_response(
                operation="replace_exact_text", field_name="replacement", value_key="absent"
            )
            good = _create_test_file_response()
            provider = _FakeProvider([bad, good])

            result = run_tests_add_workflow(self._make_request(root), provider)

            self.assertEqual(provider.call_count, 2)
            self.assertTrue(
                (result.session_path / "test_generation_error.json").exists(),
                "test_generation_error.json must be saved on schema error",
            )
            self.assertNotIn(
                result.status, {"error", "exception"},
                "Result must not be a raw exception",
            )

    def test_missing_replacement_with_retry_succeeds(self) -> None:
        """Schema retry after missing replacement produces a valid patch."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            bad = _create_missing_string_field_response(
                operation="replace_exact_text", field_name="replacement", value_key="absent"
            )
            good = _create_test_file_response()
            provider = _FakeProvider([bad, good])

            result = run_tests_add_workflow(self._make_request(root), provider)

            self.assertEqual(provider.call_count, 2)
            self.assertNotEqual(result.status, "failed_test_generation_schema")
            self.assertEqual(result.status, "test_diff_validated")

    def test_missing_replacement_with_max_retries_zero(self) -> None:
        """With max_generation_retries=0, missing replacement is a clean auditble failure."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            bad = _create_missing_string_field_response(
                operation="replace_exact_text", field_name="replacement", value_key="absent"
            )
            provider = _FakeProvider(bad)

            result = run_tests_add_workflow(
                self._make_request(root, max_generation_retries=0), provider
            )

            self.assertEqual(provider.call_count, 1)
            self.assertEqual(result.status, "failed_test_generation_schema")
            self.assertTrue(
                (result.session_path / "test_generation_error.json").exists(),
                "test_generation_error.json must be saved even when retry is disabled",
            )

    def test_missing_replacement_in_structure_retry_does_not_crash(self) -> None:
        """FileChangeOutputError in structure retry response must not escape as a raw crash."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _sample_repo(Path(tmp))
            # First response: valid parse but fails structure validation (standalone test function)
            bad_structure = _create_structure_retry_bad_response()
            # Second response (structure retry): replace_exact_text with no 'replacement'
            bad_schema = _create_missing_string_field_response(
                operation="replace_exact_text", field_name="replacement", value_key="absent"
            )
            provider = _FakeProvider([bad_structure, bad_schema])

            try:
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
                raised = None
            except Exception as exc:
                raised = exc
                result = None

            self.assertIsNone(raised, f"Workflow must not raise a raw exception; got: {raised}")
            self.assertIsNotNone(result)
            self.assertIn(
                result.status,
                {"tests_add_failed", "failed_test_generation_schema", "test_diff_validated"},
                f"Unexpected status: {result.status}",
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


