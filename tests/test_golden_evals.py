import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.diff_builder import build_unified_diff_from_file_changes
from trevvos_forge.file_change_outputs import parse_file_changes_output


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "evals"


class GoldenEvalTests(unittest.TestCase):
    def test_golden_eval_scenarios(self) -> None:
        scenario_dirs = sorted(path for path in FIXTURES_ROOT.iterdir() if path.is_dir())

        self.assertGreater(len(scenario_dirs), 0, "No golden eval scenarios found.")

        for scenario_dir in scenario_dirs:
            with self.subTest(scenario=scenario_dir.name):
                self._run_scenario(scenario_dir)

    def _run_scenario(self, scenario_dir: Path) -> None:
        input_dir = scenario_dir / "input"
        expected_dir = scenario_dir / "expected"
        expected_error_path = scenario_dir / "expected_error.txt"
        file_changes_path = scenario_dir / "file_changes.json"

        self.assertTrue(input_dir.exists(), f"Missing input directory for {scenario_dir.name}")
        self.assertTrue(file_changes_path.exists(), f"Missing file_changes.json for {scenario_dir.name}")

        with tempfile.TemporaryDirectory() as temp_dir_name:
            workspace_root = Path(temp_dir_name)
            self._copy_input_tree(input_dir, workspace_root)

            file_changes = parse_file_changes_output(file_changes_path.read_text(encoding="utf-8"))

            if expected_error_path.exists():
                expected_error = expected_error_path.read_text(encoding="utf-8").strip()
                self._assert_generation_fails(
                    workspace_root=workspace_root,
                    file_changes=file_changes,
                    expected_error=expected_error,
                )
                return

            self.assertTrue(expected_dir.exists(), f"Missing expected directory for {scenario_dir.name}")

            patch_text = build_unified_diff_from_file_changes(
                workspace_root=workspace_root,
                file_changes=file_changes,
            )
            patch_path = workspace_root / "diff.patch"
            patch_path.write_text(patch_text, encoding="utf-8", newline="\n")

            self._run_git_apply(workspace_root, patch_path, "--check")
            self._run_git_apply(workspace_root, patch_path)
            self._assert_expected_files(workspace_root, expected_dir)

    def _copy_input_tree(self, input_dir: Path, workspace_root: Path) -> None:
        for item in input_dir.iterdir():
            destination = workspace_root / item.name

            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)

    def _assert_generation_fails(self, *, workspace_root: Path, file_changes, expected_error: str) -> None:
        with self.assertRaises(Exception) as context:
            build_unified_diff_from_file_changes(
                workspace_root=workspace_root,
                file_changes=file_changes,
            )

        self.assertIn(expected_error.lower(), str(context.exception).lower())

    def _run_git_apply(self, workspace_root: Path, patch_path: Path, *extra_args: str) -> None:
        result = subprocess.run(
            ["git", "apply", *extra_args, str(patch_path)],
            cwd=workspace_root,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            result.returncode,
            0,
            f"git apply {' '.join(extra_args)} failed: {result.stderr.strip() or result.stdout.strip()}",
        )

    def _assert_expected_files(self, workspace_root: Path, expected_dir: Path) -> None:
        expected_files = sorted(path for path in expected_dir.rglob("*") if path.is_file())

        self.assertGreater(len(expected_files), 0, "Expected directory has no files.")

        for expected_file in expected_files:
            relative_path = expected_file.relative_to(expected_dir)
            actual_file = workspace_root / relative_path

            self.assertTrue(actual_file.exists(), f"Expected file was not created: {relative_path}")
            self.assertEqual(
                expected_file.read_text(encoding="utf-8"),
                actual_file.read_text(encoding="utf-8"),
                f"File content mismatch for {relative_path}",
            )


if __name__ == "__main__":
    unittest.main()
