import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.test_runner import (
    CommandSpec,
    TestRunResult,
    apply_patch_in_sandbox,
    create_project_sandbox,
    detect_test_commands,
    load_test_commands,
    load_plan_verification_commands,
    merge_test_commands,
    run_test_commands,
    run_test_command_specs,
    run_tests_in_sandbox,
    validate_safe_test_command,
    write_test_artifacts,
)
from trevvos_forge.sessions import create_session, write_patch_file, write_session_json, write_session_text
from trevvos_forge.cli import app
from typer.testing import CliRunner


def _python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class TestRunnerTests(unittest.TestCase):
    def test_load_plan_verification_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            (session_dir / "plan.json").write_text(
                json.dumps(
                    {
                        "suggested_verification_commands": [
                            "python -m py_compile main.py calculator.py",
                            "python main.py add 2 3",
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                load_plan_verification_commands(session_dir),
                [
                    "python -m py_compile main.py calculator.py",
                    "python main.py add 2 3",
                ],
            )

    def test_merge_test_commands_removes_duplicates(self) -> None:
        specs, unsafe = merge_test_commands(
            configured=["python -m unittest discover -s tests"],
            plan=[
                "python -m unittest discover -s tests",
                "python main.py add 2 3",
            ],
            selection="combined",
        )

        self.assertEqual(unsafe, [])
        self.assertEqual(
            [spec.command for spec in specs],
            [
                "python -m unittest discover -s tests",
                "python main.py add 2 3",
            ],
        )

    def test_plan_commands_selection_uses_only_plan(self) -> None:
        specs, _unsafe = merge_test_commands(
            configured=["python -m unittest discover -s tests"],
            plan=["python main.py add 2 3"],
            selection="plan",
        )

        self.assertEqual([spec.command for spec in specs], ["python main.py add 2 3"])
        self.assertEqual([spec.source for spec in specs], ["plan"])

    def test_configured_commands_selection_ignores_plan(self) -> None:
        specs, _unsafe = merge_test_commands(
            configured=["python -m unittest discover -s tests"],
            plan=["python main.py add 2 3"],
            selection="configured",
        )

        self.assertEqual([spec.command for spec in specs], ["python -m unittest discover -s tests"])
        self.assertEqual([spec.source for spec in specs], ["configured"])

    def test_unsafe_plan_command_is_blocked(self) -> None:
        safety = validate_safe_test_command("rm -rf .")

        self.assertFalse(safety.is_safe)
        self.assertIn("rm -rf", safety.reason)

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
            self.assertEqual(payload["command_sources"]["configured"], [_python_command("print('ok')")])
            self.assertIn("ok", output_path.read_text(encoding="utf-8"))

    def test_output_log_includes_command_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory) / "session"
            result = run_test_command_specs(
                command_specs=[CommandSpec(command=_python_command("print('ok')"), source="plan")],
                repo_root=Path(temporary_directory),
                timeout_seconds=10,
            )

            write_test_artifacts(session_dir, result)

            output_log = (session_dir / "test_output.log").read_text(encoding="utf-8")
            self.assertIn("Command source: plan", output_log)

    def test_create_project_sandbox_ignores_heavy_and_sensitive_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            root.mkdir()
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")

            for ignored_name in [".git", ".trevvos", ".venv", "node_modules"]:
                ignored_dir = root / ignored_name
                ignored_dir.mkdir()
                (ignored_dir / "ignored.txt").write_text("ignored\n", encoding="utf-8")

            sandbox = create_project_sandbox(root)

            try:
                self.assertTrue((sandbox / "README.md").exists())
                self.assertTrue((sandbox / "src" / "app.py").exists())
                self.assertFalse((sandbox / ".git").exists())
                self.assertFalse((sandbox / ".trevvos").exists())
                self.assertFalse((sandbox / ".venv").exists())
                self.assertFalse((sandbox / "node_modules").exists())
            finally:
                shutil.rmtree(sandbox, ignore_errors=True)

    def test_apply_patch_in_sandbox_success_keeps_original_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            root.mkdir()
            (root / "README.md").write_text("# Old\n", encoding="utf-8")
            patch_path = Path(temporary_directory) / "diff.patch"
            write_patch_file(patch_path, _readme_patch("# Old", "# New"))
            sandbox = create_project_sandbox(root)

            try:
                result = apply_patch_in_sandbox(sandbox, patch_path)

                self.assertEqual(result.status, "passed")
                self.assertEqual((sandbox / "README.md").read_text(encoding="utf-8"), "# New\n")
                self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "# Old\n")
            finally:
                shutil.rmtree(sandbox, ignore_errors=True)

    def test_run_tests_in_sandbox_patch_failure_does_not_run_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            root.mkdir()
            (root / "README.md").write_text("# Old\n", encoding="utf-8")
            patch_path = Path(temporary_directory) / "diff.patch"
            write_patch_file(patch_path, "not a patch\n")

            result = run_tests_in_sandbox(
                repo_root=root,
                patch_path=patch_path,
                commands=[_python_command("print('should not run')")],
                timeout_seconds=10,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.commands, [])
            self.assertEqual(result.sandbox["patch_apply_check"], "failed")
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "# Old\n")

    def test_run_tests_in_sandbox_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            root.mkdir()
            (root / "README.md").write_text("# Old\n", encoding="utf-8")
            patch_path = Path(temporary_directory) / "diff.patch"
            write_patch_file(patch_path, _readme_patch("# Old", "# New"))

            result = run_tests_in_sandbox(
                repo_root=root,
                patch_path=patch_path,
                commands=[_python_command("print('ok')")],
                timeout_seconds=10,
            )

            self.assertEqual(result.status, "passed")
            self.assertEqual(result.mode, "sandbox")
            self.assertEqual(result.sandbox["patch_apply_check"], "passed")
            self.assertEqual(result.sandbox["patch_apply"], "passed")
            self.assertIn("ok", result.commands[0].stdout)
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "# Old\n")
            self.assertFalse(Path(result.sandbox["runtime_path"]).exists())

    def test_run_tests_in_sandbox_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            root.mkdir()
            (root / "README.md").write_text("# Old\n", encoding="utf-8")
            patch_path = Path(temporary_directory) / "diff.patch"
            write_patch_file(patch_path, _readme_patch("# Old", "# New"))

            result = run_tests_in_sandbox(
                repo_root=root,
                patch_path=patch_path,
                commands=[_python_command("import sys; sys.exit(2)")],
                timeout_seconds=10,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.commands[0].exit_code, 2)

    def test_artifacts_include_skipped_unsafe_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory) / "session"
            result = TestRunResult(
                status="failed",
                commands=[],
                summary={"total": 0, "passed": 0, "failed": 1, "timed_out": 0},
                mode="sandbox",
                command_sources={
                    "configured": [],
                    "plan": [],
                    "executed": [],
                    "skipped_unsafe": [
                        {
                            "command": "rm -rf .",
                            "is_safe": False,
                            "reason": "Unsafe command pattern: rm -rf",
                        }
                    ],
                },
            )

            write_test_artifacts(session_dir, result)

            payload = json.loads((session_dir / "test_results.json").read_text(encoding="utf-8"))
            output_log = (session_dir / "test_output.log").read_text(encoding="utf-8")

            self.assertEqual(payload["command_sources"]["skipped_unsafe"][0]["command"], "rm -rf .")
            self.assertIn("Skipped unsafe commands", output_log)

    def test_run_tests_in_sandbox_keep_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            root.mkdir()
            (root / "README.md").write_text("# Old\n", encoding="utf-8")
            patch_path = Path(temporary_directory) / "diff.patch"
            write_patch_file(patch_path, _readme_patch("# Old", "# New"))

            result = run_tests_in_sandbox(
                repo_root=root,
                patch_path=patch_path,
                commands=[_python_command("print('ok')")],
                timeout_seconds=10,
                keep_sandbox=True,
            )
            sandbox_path = Path(result.sandbox["path"])

            try:
                self.assertTrue(sandbox_path.exists())
                self.assertEqual((sandbox_path / "README.md").read_text(encoding="utf-8"), "# New\n")
            finally:
                shutil.rmtree(sandbox_path, ignore_errors=True)

    def test_sandbox_artifacts_include_mode_and_patch_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project"
            root.mkdir()
            session_dir = Path(temporary_directory) / "session"
            (root / "README.md").write_text("# Old\n", encoding="utf-8")
            patch_path = Path(temporary_directory) / "diff.patch"
            write_patch_file(patch_path, _readme_patch("# Old", "# New"))
            result = run_tests_in_sandbox(
                repo_root=root,
                patch_path=patch_path,
                commands=[_python_command("print('ok')")],
                timeout_seconds=10,
            )

            write_test_artifacts(session_dir, result)

            payload = json.loads((session_dir / "test_results.json").read_text(encoding="utf-8"))
            output_log = (session_dir / "test_output.log").read_text(encoding="utf-8")

            self.assertEqual(payload["mode"], "sandbox")
            self.assertTrue(payload["sandbox"]["enabled"])
            self.assertEqual(payload["sandbox"]["patch_apply_check"], "passed")
            self.assertEqual(payload["sandbox"]["patch_apply"], "passed")
            self.assertIn("Mode: sandbox", output_log)
            self.assertIn("Patch apply check: passed", output_log)

    def test_cli_sandbox_runs_plan_command(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "test", command="plan")
            write_session_json(
                session,
                "plan.json",
                {"suggested_verification_commands": [f'"{sys.executable}" main.py']},
            )
            write_patch_file(session.path / "diff.patch", _create_file_patch("main.py", "print('plan ok')\n"))

            result = runner.invoke(
                app,
                ["test", "--sandbox", "--plan-commands", "--yes", "--path", str(root)],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads((session.path / "test_results.json").read_text(encoding="utf-8"))
            output_log = (session.path / "test_output.log").read_text(encoding="utf-8")

            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["command_sources"]["plan"], [f'"{sys.executable}" main.py'])
            self.assertIn("Command source: plan", output_log)

    def test_cli_sandbox_plan_command_failure(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            session = create_session(root, "test", command="plan")
            write_session_json(
                session,
                "plan.json",
                {"suggested_verification_commands": [f'"{sys.executable}" -c "import sys; sys.exit(2)"']},
            )
            write_patch_file(session.path / "diff.patch", _create_file_patch("README.md", "# Demo\n"))

            result = runner.invoke(
                app,
                ["test", "--sandbox", "--plan-commands", "--yes", "--path", str(root)],
            )

            self.assertEqual(result.exit_code, 1)
            payload = json.loads((session.path / "test_results.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["commands"][0]["exit_code"], 2)

    def test_working_tree_mode_uses_configured_by_default(self) -> None:
        specs, _unsafe = merge_test_commands(
            configured=[_python_command("print('configured')")],
            plan=[_python_command("print('plan')")],
            selection="configured",
        )

        self.assertEqual([spec.source for spec in specs], ["configured"])

def _readme_patch(old_heading: str, new_heading: str) -> str:
    return (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        f"-{old_heading}\n"
        f"+{new_heading}\n"
    )


def _create_file_patch(path: str, content: str) -> str:
    lines = content.splitlines()
    added = "\n".join(f"+{line}" for line in lines)

    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{added}\n"
    )


if __name__ == "__main__":
    unittest.main()
