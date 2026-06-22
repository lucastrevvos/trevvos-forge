import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.prompt_catalog import get_prompt
from trevvos_forge.test_runner import TestRunResult
from trevvos_forge.test_generation import (
    TEST_FILE_ERROR,
    SymbolInfo,
    build_test_generation_target,
    detect_existing_tests_for_symbols,
    detect_testable_python_symbols,
    select_test_generation_commands,
    validate_test_file_path,
)
from trevvos_forge.timeline import read_timeline


class TestsAddCommandTests(unittest.TestCase):
    def test_detects_existing_test_by_name(self) -> None:
        check = detect_existing_tests_for_symbols(
            test_file_content="def test_divide_by_zero():\n    assert True\n",
            symbols=["divide"],
        )

        self.assertTrue(check["divide"]["covered"])
        self.assertIn("test_divide_by_zero", check["divide"]["evidence"])

    def test_detects_existing_test_by_call_body(self) -> None:
        check = detect_existing_tests_for_symbols(
            test_file_content="def test_zero_division():\n    divide(1, 0)\n",
            symbols=["divide"],
        )

        self.assertTrue(check["divide"]["covered"])
        self.assertIn("calls divide", check["divide"]["evidence"])

    def test_missing_existing_test_is_not_covered(self) -> None:
        check = detect_existing_tests_for_symbols(
            test_file_content="def test_add():\n    add(1, 2)\n",
            symbols=["multiply"],
        )

        self.assertFalse(check["multiply"]["covered"])

    def test_all_detects_public_functions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))

            symbols = detect_testable_python_symbols(root / "calculator.py")
            names = [symbol.name for symbol in symbols]

            self.assertEqual(names, ["add", "subtract", "multiply", "divide"])
            self.assertNotIn("_helper", names)
            self.assertNotIn("main", names)

    def test_existing_symbol_calls_provider(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Requested symbol: divide", provider.prompt)

    def test_symbol_and_all_are_mutually_exclusive(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(
                    app,
                    ["tests", "add", "calculator.py", "--symbol", "divide", "--all", "--path", str(root)],
                )

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Use either --symbol or --all, not both.", result.output)
            build_provider.assert_not_called()

    def test_missing_symbol_and_all_fails_without_provider(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Specify --symbol <name> or --all.", result.output)
            build_provider.assert_not_called()

    def test_missing_symbol_fails_without_provider(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "banana", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Symbol `banana` not found in calculator.py", result.output)
            build_provider.assert_not_called()

    def test_detects_existing_test_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            (root / "tests").mkdir()
            (root / "tests" / "test_calculator.py").write_text("import unittest\n", encoding="utf-8")

            target = build_test_generation_target(
                workspace_root=root,
                source_path=Path("calculator.py"),
                symbol="divide",
            )

            self.assertEqual(target.test_file, "tests/test_calculator.py")
            self.assertTrue(target.test_file_exists)

    def test_chooses_probable_test_file_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))

            target = build_test_generation_target(
                workspace_root=root,
                source_path=Path("calculator.py"),
                symbol="divide",
            )

            self.assertEqual(target.test_file, "tests/test_calculator.py")
            self.assertFalse(target.test_file_exists)

    def test_validates_test_file_path(self) -> None:
        validate_test_file_path("tests/test_calculator.py")

        with self.assertRaises(Exception) as context:
            validate_test_file_path("calculator.py")
        self.assertEqual(str(context.exception), TEST_FILE_ERROR)

    def test_prompt_contains_test_generation_rules(self) -> None:
        prompt = get_prompt("test_generation").render(test_generation_context="context")

        self.assertIn("Only create or modify test files", prompt)
        self.assertIn("Never modify production source files", prompt)
        self.assertIn("Preserve existing tests", prompt)
        self.assertIn("Return ONLY valid JSON", prompt)
        self.assertIn("use unittest to avoid adding external dependencies", prompt)
        self.assertIn("Mode: all_symbols", prompt)
        self.assertIn("generate tests for every listed symbol", prompt)

    def test_all_prompt_receives_all_symbols(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_all_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--all", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Mode: all_symbols", provider.prompt)
            for symbol in ["add", "subtract", "multiply", "divide"]:
                self.assertIn(f"- {symbol}", provider.prompt)

    def test_all_metadata_records_symbols(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_all_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--all", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            metadata = _read_json(_only_session(root) / "test_generation_metadata.json")

            self.assertTrue(metadata["all"])
            self.assertIsNone(metadata["symbol"])
            self.assertEqual(metadata["symbols"], ["add", "subtract", "multiply", "divide"])

    def test_symbol_existing_test_skips_provider(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_calculator.py").write_text(
                "from calculator import divide\n\n"
                "def test_divide_by_zero():\n"
                "    divide(1, 1)\n",
                encoding="utf-8",
            )

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            build_provider.assert_not_called()
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "test_generation_metadata.json")
            existing = _read_json(session_dir / "existing_tests_check.json")

            self.assertEqual(metadata["status"], "skipped_existing_tests")
            self.assertFalse(metadata["provider_called"])
            self.assertEqual(existing["status"], "all_covered")
            self.assertFalse((session_dir / "test_diff.patch").exists())

    def test_symbol_force_calls_provider_with_existing_tests_context(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_calculator.py").write_text(
                "from calculator import divide\n\n"
                "def test_divide_by_zero():\n"
                "    divide(1, 1)\n",
                encoding="utf-8",
            )
            provider = _FakeProvider(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "tests/test_calculator.py",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "append_to_file",
                                "insert": "\n\ndef test_divide_negative_values():\n    assert divide(-4, 2) == -2\n",
                            }
                        ]
                    }
                )
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["tests", "add", "calculator.py", "--symbol", "divide", "--force", "--path", str(root)],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Existing tests analysis:", provider.prompt)
            self.assertIn("Some or all symbols may already have tests", provider.prompt)
            metadata = _read_json(_only_session(root) / "test_generation_metadata.json")
            self.assertTrue(metadata["provider_called"])

    def test_all_partial_generates_only_missing_symbols(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_calculator.py").write_text(
                "from calculator import add, divide\n\n"
                "def test_add_returns_sum():\n"
                "    add(1, 2)\n\n"
                "def test_divide_by_zero():\n"
                "    divide(1, 1)\n",
                encoding="utf-8",
            )
            provider = _FakeProvider(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "tests/test_calculator.py",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "append_to_file",
                                "insert": (
                                    "\n\ndef test_subtract():\n    assert True\n\n"
                                    "def test_multiply():\n    assert True\n"
                                ),
                            }
                        ]
                    }
                )
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--all", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            symbols_section = provider.prompt.split("Symbols to test:", 1)[1].split("Target test file:", 1)[0]
            self.assertIn("- subtract", symbols_section)
            self.assertIn("- multiply", symbols_section)
            self.assertNotIn("- add", symbols_section)
            self.assertNotIn("- divide", symbols_section)
            metadata = _read_json(_only_session(root) / "test_generation_metadata.json")
            self.assertEqual(metadata["symbols_original"], ["add", "subtract", "multiply", "divide"])
            self.assertEqual(metadata["symbols"], ["subtract", "multiply"])
            self.assertEqual(metadata["existing_tests"]["status"], "partial")

    def test_all_fully_covered_skips_provider(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_calculator.py").write_text(
                "from calculator import add, subtract, multiply, divide\n\n"
                "def test_add():\n    add(1, 2)\n"
                "def test_subtract():\n    subtract(2, 1)\n"
                "def test_multiply():\n    multiply(2, 2)\n"
                "def test_divide():\n    divide(4, 2)\n",
                encoding="utf-8",
            )

            with patch("trevvos_forge.cli.build_provider") as build_provider:
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--all", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            build_provider.assert_not_called()
            metadata = _read_json(_only_session(root) / "test_generation_metadata.json")
            self.assertEqual(metadata["status"], "skipped_existing_tests")
            self.assertFalse(metadata["provider_called"])

    def test_all_force_calls_provider_when_all_covered(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_calculator.py").write_text(
                "from calculator import add, subtract, multiply, divide\n\n"
                "def test_add():\n    add(1, 2)\n"
                "def test_subtract():\n    subtract(2, 1)\n"
                "def test_multiply():\n    multiply(2, 2)\n"
                "def test_divide():\n    divide(4, 2)\n",
                encoding="utf-8",
            )
            provider = _FakeProvider(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "tests/test_calculator.py",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "append_to_file",
                                "insert": "\n\ndef test_extra_edge_case():\n    assert True\n",
                            }
                        ]
                    }
                )
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--all", "--force", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Some or all symbols may already have tests", provider.prompt)

    def test_dry_run_saves_artifacts_without_changing_working_tree(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertFalse((root / "tests" / "test_calculator.py").exists())
            session_dir = _only_session(root)
            metadata = _read_json(session_dir / "test_generation_metadata.json")

            self.assertTrue((session_dir / "test_diff.patch").exists())
            self.assertTrue((session_dir / "test_sandbox_results.json").exists())
            sandbox_results = _read_json(session_dir / "test_sandbox_results.json")
            self.assertEqual(sandbox_results["status"], "passed")
            self.assertEqual(sandbox_results["command_source"], "targeted")
            self.assertEqual(sandbox_results["commands"][0]["command"], "python -m unittest tests.test_calculator")
            self.assertEqual(sandbox_results["commands"][0]["source"], "targeted_test_file")
            self.assertFalse(metadata["write"])
            self.assertEqual(metadata["sandbox"]["status"], "passed")
            self.assertEqual(metadata["sandbox"]["command_source"], "targeted")
            self.assertTrue(metadata["write_allowed"])
            self.assertEqual(metadata["test_file"], "tests/test_calculator.py")

    def test_dry_run_keeps_sandbox_when_requested(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    [
                        "tests",
                        "add",
                        "calculator.py",
                        "--symbol",
                        "divide",
                        "--keep-sandbox",
                        "--path",
                        str(root),
                    ],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertFalse((root / "tests" / "test_calculator.py").exists())
            sandbox_results = _read_json(_only_session(root) / "test_sandbox_results.json")
            sandbox_path = Path(sandbox_results["sandbox"]["path"])

            try:
                self.assertTrue((sandbox_path / "tests" / "test_calculator.py").exists())
                self.assertTrue(sandbox_results["sandbox"]["kept"])
            finally:
                _remove_tree(sandbox_path)

    def test_all_dry_run_does_not_change_working_tree(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_all_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--all", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertFalse((root / "tests" / "test_calculator.py").exists())
            self.assertTrue((_only_session(root) / "test_diff.patch").exists())

    def test_write_applies_patch_and_does_not_modify_source(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            original_source = (root / "calculator.py").read_text(encoding="utf-8")
            provider = _FakeProvider(_create_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["tests", "add", "calculator.py", "--symbol", "divide", "--write", "--yes", "--path", str(root)],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual((root / "calculator.py").read_text(encoding="utf-8"), original_source)
            self.assertTrue((root / "tests" / "test_calculator.py").exists())
            self.assertTrue((_only_session(root) / "test_apply_result.json").exists())

    def test_write_blocks_when_sandbox_fails(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            original_source = (root / "calculator.py").read_text(encoding="utf-8")
            provider = _FakeProvider(_create_failing_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["tests", "add", "calculator.py", "--symbol", "divide", "--write", "--yes", "--path", str(root)],
                )

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Cannot write test patch because sandbox tests failed", result.output)
            self.assertEqual((root / "calculator.py").read_text(encoding="utf-8"), original_source)
            self.assertFalse((root / "tests" / "test_calculator.py").exists())
            session_dir = _only_session(root)
            sandbox_results = _read_json(session_dir / "test_sandbox_results.json")
            metadata = _read_json(session_dir / "test_generation_metadata.json")

            self.assertEqual(sandbox_results["status"], "failed")
            self.assertFalse(metadata["write_allowed"])
            self.assertFalse((session_dir / "test_apply_result.json").exists())

    def test_all_write_applies_patch_and_preserves_source(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            original_source = (root / "calculator.py").read_text(encoding="utf-8")
            provider = _FakeProvider(_create_all_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["tests", "add", "calculator.py", "--all", "--write", "--yes", "--path", str(root)],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual((root / "calculator.py").read_text(encoding="utf-8"), original_source)
            content = (root / "tests" / "test_calculator.py").read_text(encoding="utf-8")
            for test_name in ["test_add", "test_subtract", "test_multiply", "test_divide"]:
                self.assertIn(test_name, content)

    def test_rejects_provider_change_outside_tests(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(
                json.dumps(
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
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn(TEST_FILE_ERROR, result.output)
            self.assertFalse((root / "test_diff.patch").exists())

    def test_all_rejects_provider_change_outside_tests(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(
                json.dumps(
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
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--all", "--path", str(root)])

            self.assertEqual(result.exit_code, 1)
            self.assertIn(TEST_FILE_ERROR, result.output)

    def test_append_preserves_existing_test_content(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            tests_dir = root / "tests"
            tests_dir.mkdir()
            existing = "def test_existing():\n    assert True\n"
            (tests_dir / "test_calculator.py").write_text(existing, encoding="utf-8")
            provider = _FakeProvider(
                json.dumps(
                    {
                        "changes": [
                            {
                                "path": "tests/test_calculator.py",
                                "change_type": "modified",
                                "mode": "operation_based_edit",
                                "operation": "append_to_file",
                                "insert": (
                                    "\n\nimport unittest\n\n"
                                    "class TestGeneratedCalculator(unittest.TestCase):\n"
                                    "    def test_divide_new(self):\n"
                                    "        self.assertTrue(True)\n"
                                ),
                            }
                        ]
                    }
                )
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["tests", "add", "calculator.py", "--symbol", "divide", "--write", "--yes", "--path", str(root)],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            content = (tests_dir / "test_calculator.py").read_text(encoding="utf-8")
            self.assertIn("def test_existing", content)
            self.assertIn("def test_divide_new", content)

    def test_git_apply_check_and_artifacts_are_saved(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            session_dir = _only_session(root)
            validation = _read_json(session_dir / "test_generation_validation.json")

            self.assertEqual(validation["git_apply_check"], "passed")
            for artifact in [
                "test_generation_prompt.md",
                "test_generation_raw_response.json",
                "test_file_changes.json",
                "test_diff.patch",
                "test_generation_metadata.json",
                "test_generation_summary.md",
                "test_sandbox_results.json",
                "test_sandbox_output.log",
            ]:
                self.assertTrue((session_dir / artifact).exists(), artifact)

    def test_sandbox_output_log_contains_command(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            output_log = (_only_session(root) / "test_sandbox_output.log").read_text(encoding="utf-8")

            self.assertIn("python -m unittest tests.test_calculator", output_log)
            self.assertIn("Patch apply: passed", output_log)

    def test_configured_test_command_is_used_for_sandbox(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            (root / ".trevvos").mkdir()
            (root / ".trevvos" / "config.json").write_text(
                json.dumps({"test_commands": ["python -m unittest discover -s tests"]}),
                encoding="utf-8",
            )
            provider = _FakeProvider(_create_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            sandbox_results = _read_json(_only_session(root) / "test_sandbox_results.json")

            self.assertEqual(sandbox_results["command_source"], "config")
            self.assertEqual(sandbox_results["symbol_selector"]["reason"], "config_override")
            self.assertEqual(sandbox_results["commands"][0]["source"], "config")

    def test_selects_pytest_when_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            target = build_test_generation_target(
                workspace_root=root,
                source_path=Path("calculator.py"),
                symbol="divide",
            )

            commands, source, selector = select_test_generation_commands(workspace_root=root, target=target)

            self.assertEqual(commands, ["pytest tests/test_calculator.py -k divide"])
            self.assertEqual(source, "targeted_symbol")
            self.assertTrue(selector["enabled"])
            self.assertEqual(selector["symbol"], "divide")

    def test_pytest_all_mode_does_not_use_symbol_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            target = build_test_generation_target(
                workspace_root=root,
                source_path=Path("calculator.py"),
                symbol=None,
                all_symbols=True,
            )

            commands, source, selector = select_test_generation_commands(workspace_root=root, target=target)

            self.assertEqual(commands, ["pytest tests/test_calculator.py"])
            self.assertEqual(source, "targeted")
            self.assertFalse(selector["enabled"])
            self.assertEqual(selector["reason"], "all_symbols_mode")

    def test_sandbox_uses_targeted_pytest_command(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            provider = _FakeProvider(_create_pytest_test_file_response())
            captured: dict[str, list[str]] = {}

            def fake_sandbox(**kwargs):
                command_specs = kwargs["command_specs"]
                captured["commands"] = [spec.command for spec in command_specs]
                captured["sources"] = [spec.source for spec in command_specs]
                return TestRunResult(
                    status="passed",
                    commands=[],
                    summary={"total": 0, "passed": 0, "failed": 0, "timed_out": 0},
                    mode="sandbox",
                    sandbox={
                        "enabled": True,
                        "kept": False,
                        "path": None,
                        "patch_apply_check": "passed",
                        "patch_apply": "passed",
                    },
                )

            with (
                patch("trevvos_forge.cli.build_provider", return_value=provider),
                patch("trevvos_forge.cli.run_test_specs_in_sandbox", side_effect=fake_sandbox),
            ):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(captured["commands"], ["pytest tests/test_calculator.py -k divide"])
            self.assertEqual(captured["sources"], ["targeted_symbol"])
            sandbox_results = _read_json(_only_session(root) / "test_sandbox_results.json")
            metadata = _read_json(_only_session(root) / "test_generation_metadata.json")
            self.assertEqual(sandbox_results["command_source"], "targeted_symbol")
            self.assertTrue(sandbox_results["symbol_selector"]["enabled"])
            self.assertEqual(metadata["sandbox"]["command_source"], "targeted_symbol")
            self.assertTrue(metadata["sandbox"]["symbol_selector"]["enabled"])

    def test_selects_unittest_target_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            target = build_test_generation_target(
                workspace_root=root,
                source_path=Path("calculator.py"),
                symbol="divide",
            )

            commands, source, selector = select_test_generation_commands(workspace_root=root, target=target)

            self.assertEqual(commands, ["python -m unittest tests.test_calculator"])
            self.assertEqual(source, "targeted")
            self.assertFalse(selector["enabled"])
            self.assertEqual(selector["reason"], "framework_not_supported")

    def test_unknown_framework_falls_back_to_discover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            target = build_test_generation_target(
                workspace_root=root,
                source_path=Path("calculator.py"),
                symbol="divide",
            )
            target = replace(target, framework="unknown")

            commands, source, selector = select_test_generation_commands(workspace_root=root, target=target)

            self.assertEqual(commands, ["python -m unittest discover -s tests"])
            self.assertEqual(source, "fallback")
            self.assertFalse(selector["enabled"])

    def test_windows_test_file_path_is_normalized_for_target_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            target = build_test_generation_target(
                workspace_root=root,
                source_path=Path("calculator.py"),
                symbol="divide",
                requested_test_file=Path("tests") / "test_calculator.py",
            )
            target = replace(target, test_file="tests\\test_calculator.py", framework="pytest")

            commands, source, selector = select_test_generation_commands(workspace_root=root, target=target)

            self.assertEqual(commands, ["pytest tests/test_calculator.py -k divide"])
            self.assertEqual(source, "targeted_symbol")
            self.assertTrue(selector["enabled"])

            target = replace(target, framework="unittest")
            commands, source, selector = select_test_generation_commands(workspace_root=root, target=target)

            self.assertEqual(commands, ["python -m unittest tests.test_calculator"])
            self.assertEqual(source, "targeted")
            self.assertFalse(selector["enabled"])

    def test_unsafe_symbol_does_not_enter_pytest_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            target = build_test_generation_target(
                workspace_root=root,
                source_path=Path("calculator.py"),
                symbol="divide",
            )
            target = replace(target, symbol=SymbolInfo("divide; rm -rf", "function", 1), framework="pytest")

            commands, source, selector = select_test_generation_commands(workspace_root=root, target=target)

            self.assertEqual(commands, ["pytest tests/test_calculator.py"])
            self.assertEqual(source, "targeted")
            self.assertFalse(selector["enabled"])
            self.assertEqual(selector["reason"], "unsafe_symbol")
            self.assertNotIn("rm -rf", commands[0])

    def test_suspicious_test_file_path_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            target = build_test_generation_target(
                workspace_root=root,
                source_path=Path("calculator.py"),
                symbol="divide",
            )
            target = replace(target, test_file="../tests/test_calculator.py", framework="unittest")

            commands, source, selector = select_test_generation_commands(workspace_root=root, target=target)

            self.assertEqual(commands, ["python -m unittest discover -s tests"])
            self.assertEqual(source, "fallback")
            self.assertFalse(selector["enabled"])

    def test_timeline_records_sandbox_events(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--symbol", "divide", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            events = [event["event"] for event in read_timeline(_only_session(root))]

            self.assertIn("tests_add_sandbox_started", events)
            self.assertIn("tests_add_sandbox_completed", events)

    def test_help(self) -> None:
        result = CliRunner().invoke(app, ["tests", "add", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--symbol", result.output)
        self.assertIn("--all", result.output)
        self.assertIn("--write", result.output)
        self.assertIn("--force", result.output)
        self.assertIn("--keep-sandbox", result.output)

    def test_json_output(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(
                    app,
                    ["tests", "add", "calculator.py", "--symbol", "divide", "--json", "--path", str(root)],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["command"], "tests add")
            self.assertEqual(payload["files_changed"], ["tests/test_calculator.py"])

    def test_all_summary_lists_symbols(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _sample_repo(Path(temporary_directory))
            provider = _FakeProvider(_create_all_test_file_response())

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["tests", "add", "calculator.py", "--all", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            summary = (_only_session(root) / "test_generation_summary.md").read_text(encoding="utf-8")
            self.assertIn("## Symbols targeted", summary)
            for symbol in ["add", "subtract", "multiply", "divide"]:
                self.assertIn(f"- {symbol}", summary)


def _sample_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "calculator.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n\n"
        "def subtract(a, b):\n"
        "    return a - b\n\n"
        "def multiply(a, b):\n"
        "    return a * b\n\n"
        "def divide(a, b):\n"
        "    if b == 0:\n"
        "        raise ValueError('division by zero')\n"
        "    return a / b\n\n"
        "def _helper():\n"
        "    return 'private'\n\n"
        "def main():\n"
        "    return None\n",
        encoding="utf-8",
    )
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


def _create_pytest_test_file_response() -> str:
    return json.dumps(
        {
            "changes": [
                {
                    "path": "tests/test_calculator.py",
                    "change_type": "created",
                    "mode": "operation_based_edit",
                    "operation": "create_file",
                    "content": (
                        "import pytest\n\n"
                        "from calculator import divide\n\n\n"
                        "def test_divide_by_zero_raises_value_error():\n"
                        "    with pytest.raises(ValueError):\n"
                        "        divide(10, 0)\n"
                    ),
                }
            ]
        }
    )


def _create_all_test_file_response() -> str:
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


def _only_session(root: Path) -> Path:
    return next((root / ".trevvos" / "sessions").iterdir())


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _remove_tree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt = ""

    def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


if __name__ == "__main__":
    unittest.main()
