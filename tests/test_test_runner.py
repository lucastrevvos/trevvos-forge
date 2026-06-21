import json
import sys
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.test_runner import (
    detect_test_commands,
    load_test_commands,
    run_test_commands,
    write_test_artifacts,
)


def _python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class TestRunnerTests(unittest.TestCase):
    def test_loads_commands_from_trevvos_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_dir = root / ".trevvos"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps(
                    {
                        "test_commands": [
                            "python -m unittest discover -s tests",
                            "python -m compileall trevvos_forge tests",
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                load_test_commands(root),
                [
                    "python -m unittest discover -s tests",
                    "python -m compileall trevvos_forge tests",
                ],
            )

    def test_detects_python_project_with_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
            (root / "tests").mkdir()

            commands = detect_test_commands(root)

            self.assertIn("python -m unittest discover -s tests", commands)

    def test_empty_project_has_no_detected_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = run_test_commands(
                commands=detect_test_commands(Path(temporary_directory)),
                repo_root=Path(temporary_directory),
                timeout_seconds=1,
            )

            self.assertEqual(result.status, "not_configured")
            self.assertEqual(result.summary["total"], 0)

    def test_runs_successful_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = run_test_commands(
                commands=[_python_command("print('ok')")],
                repo_root=Path(temporary_directory),
                timeout_seconds=10,
            )

            self.assertEqual(result.status, "passed")
            self.assertEqual(result.commands[0].exit_code, 0)
            self.assertIn("ok", result.commands[0].stdout)

    def test_runs_failing_command_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = run_test_commands(
                commands=[
                    _python_command("import sys; sys.exit(3)"),
                    _python_command("print('should not run')"),
                ],
                repo_root=Path(temporary_directory),
                timeout_seconds=10,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.commands[0].exit_code, 3)
            self.assertEqual(len(result.commands), 1)

    def test_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = run_test_commands(
                commands=[_python_command("import time; time.sleep(2)")],
                repo_root=Path(temporary_directory),
                timeout_seconds=1,
            )

            self.assertEqual(result.status, "timed_out")
            self.assertIsNone(result.commands[0].exit_code)

    def test_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory) / "session"
            result = run_test_commands(
                commands=[_python_command("print('ok')")],
                repo_root=Path(temporary_directory),
                timeout_seconds=10,
            )

            write_test_artifacts(session_dir, result)

            results_path = session_dir / "test_results.json"
            output_path = session_dir / "test_output.log"

            self.assertTrue(results_path.exists())
            self.assertTrue(output_path.exists())

            payload = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["passed"], 1)
            self.assertIn("ok", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
