import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.prompt_catalog import get_prompt
from trevvos_forge.test_generation import (
    TEST_FILE_ERROR,
    build_test_generation_target,
    detect_testable_python_symbols,
    validate_test_file_path,
)


class TestsAddCommandTests(unittest.TestCase):
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
            self.assertFalse(metadata["write"])
            self.assertEqual(metadata["test_file"], "tests/test_calculator.py")

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
                                "insert": "\n\ndef test_divide_new():\n    assert True\n",
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
            ]:
                self.assertTrue((session_dir / artifact).exists(), artifact)

    def test_help(self) -> None:
        result = CliRunner().invoke(app, ["tests", "add", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--symbol", result.output)
        self.assertIn("--all", result.output)
        self.assertIn("--write", result.output)

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


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt = ""

    def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


if __name__ == "__main__":
    unittest.main()
