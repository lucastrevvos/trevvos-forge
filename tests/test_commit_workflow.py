import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.commit_workflow import (
    CommitResult,
    build_commit_plan,
    build_deterministic_commit_message,
    extract_patch_paths,
    parse_commit_message_response,
    render_commit_message,
    run_git_commit,
    write_commit_artifacts,
)
from trevvos_forge.exceptions import CommitError
from trevvos_forge.sessions import write_patch_file


class CommitWorkflowTests(unittest.TestCase):
    def test_extract_patch_paths_from_diff(self) -> None:
        patch = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""

        self.assertEqual(extract_patch_paths(patch), ["README.md"])

    def test_extract_patch_paths_uses_new_path_for_created_file(self) -> None:
        patch = """diff --git a/docs/usage.md b/docs/usage.md
new file mode 100644
--- /dev/null
+++ b/docs/usage.md
@@ -0,0 +1 @@
+hello
"""

        self.assertEqual(extract_patch_paths(patch), ["docs/usage.md"])

    def test_deterministic_commit_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            (session_dir / "change_summary.md").write_text(
                "# Change Summary\n\n## Patch Summary\n\n- Added sandbox test mode.\n",
                encoding="utf-8",
            )

            message = build_deterministic_commit_message(
                session_dir,
                ["trevvos_forge/test_runner.py"],
            )

            self.assertTrue(message.subject)
            self.assertIn("sandbox", message.subject.lower())

    def test_commit_plan_with_related_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _init_repo(Path(temporary_directory) / "repo")
            session_dir = _create_session(root, ["README.md"])
            (root / "README.md").write_text("# New\n", encoding="utf-8")

            plan = build_commit_plan(session_dir=session_dir, repo_root=root)

            self.assertEqual(plan.files_to_stage, ["README.md"])
            self.assertEqual(plan.unrelated_changes, [])

    def test_commit_plan_detects_unrelated_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _init_repo(Path(temporary_directory) / "repo")
            session_dir = _create_session(root, ["README.md"])
            (root / "README.md").write_text("# New\n", encoding="utf-8")
            (root / "notes.txt").write_text("notes\n", encoding="utf-8")

            plan = build_commit_plan(session_dir=session_dir, repo_root=root)

            self.assertEqual(plan.files_to_stage, ["README.md"])
            self.assertEqual(plan.unrelated_changes, ["notes.txt"])

    def test_dry_run_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _init_repo(Path(temporary_directory) / "repo")
            session_dir = _create_session(root, ["README.md"])
            (root / "README.md").write_text("# New\n", encoding="utf-8")
            plan = build_commit_plan(session_dir=session_dir, repo_root=root)
            result = CommitResult(
                status="dry_run",
                files_staged=plan.files_to_stage,
                message_subject=plan.message.subject,
            )

            write_commit_artifacts(session_dir=session_dir, plan=plan, result=result)

            self.assertTrue((session_dir / "commit_message.txt").exists())
            self.assertTrue((session_dir / "commit_plan.json").exists())
            self.assertTrue((session_dir / "commit_result.json").exists())
            payload = json.loads((session_dir / "commit_result.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(_git(root, ["rev-list", "--count", "HEAD"]).stdout.strip(), "1")

    def test_git_commit_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _init_repo(Path(temporary_directory) / "repo")
            session_dir = _create_session(root, ["README.md"])
            (root / "README.md").write_text("# New\n", encoding="utf-8")
            plan = build_commit_plan(session_dir=session_dir, repo_root=root)

            result = run_git_commit(
                repo_root=root,
                files=plan.files_to_stage,
                message_text=render_commit_message(plan.message),
            )

            self.assertEqual(result.status, "committed")
            self.assertTrue(result.commit_hash)
            self.assertNotIn("README.md", _git(root, ["status", "--porcelain"]).stdout)
            self.assertEqual(_git(root, ["rev-list", "--count", "HEAD"]).stdout.strip(), "2")

    def test_blocks_when_no_related_files_modified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _init_repo(Path(temporary_directory) / "repo")
            session_dir = _create_session(root, ["README.md"])

            with self.assertRaisesRegex(CommitError, "no related session files"):
                build_commit_plan(session_dir=session_dir, repo_root=root)

    def test_blocks_existing_staged_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = _init_repo(Path(temporary_directory) / "repo")
            session_dir = _create_session(root, ["README.md"])
            (root / "README.md").write_text("# New\n", encoding="utf-8")
            (root / "notes.txt").write_text("notes\n", encoding="utf-8")
            _git(root, ["add", "--", "notes.txt"])

            with self.assertRaisesRegex(CommitError, "staged changes already exist"):
                build_commit_plan(session_dir=session_dir, repo_root=root)

    def test_parse_commit_message_response(self) -> None:
        message = parse_commit_message_response(
            json.dumps(
                {
                    "subject": "Add sandbox test mode",
                    "body": ["Adds sandbox execution."],
                    "confidence": "medium",
                }
            )
        )

        self.assertEqual(message.subject, "Add sandbox test mode")
        self.assertEqual(message.body, ["Adds sandbox execution."])

    def test_parse_commit_message_response_failure(self) -> None:
        with self.assertRaises(CommitError):
            parse_commit_message_response("not json")


def _init_repo(root: Path) -> Path:
    root.mkdir()
    _git(root, ["init"])
    _git(root, ["config", "user.email", "test@example.com"])
    _git(root, ["config", "user.name", "Test User"])
    (root / "README.md").write_text("# Old\n", encoding="utf-8")
    _git(root, ["add", "--", "README.md"])
    _git(root, ["commit", "-m", "Initial commit"])

    return root


def _create_session(root: Path, patch_paths: list[str]) -> Path:
    session_dir = root / ".trevvos" / "sessions" / "test-session"
    session_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps({"id": "test-session"}),
        encoding="utf-8",
    )
    write_patch_file(
        session_dir / "diff.patch",
        "".join(_patch_for_path(path) for path in patch_paths),
    )
    (session_dir / "change_summary.md").write_text(
        "# Change Summary\n\n## Patch Summary\n\n- Updated README.\n",
        encoding="utf-8",
    )

    return session_dir


def _patch_for_path(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-# Old\n"
        "+# New\n"
    )


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()
