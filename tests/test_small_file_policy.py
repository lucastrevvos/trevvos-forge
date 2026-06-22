import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from trevvos_forge.cli import app
from trevvos_forge.file_change_outputs import FileChange, FileChangesOutput
from trevvos_forge.sessions import create_session, write_session_json, write_session_text
from trevvos_forge.small_file_policy import detect_small_file_structural_edit_risk


class SmallFilePolicyTests(unittest.TestCase):
    def test_warning_for_multiple_local_operations_in_small_main(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_small_main(root / "main.py", line_count=50)

            warnings = detect_small_file_structural_edit_risk(
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="main.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="insert_after_line",
                            target="subparsers = parser.add_subparsers(dest='command')",
                            insert="sqrt_parser = subparsers.add_parser('sqrt')\n",
                        ),
                        FileChange(
                            path="main.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="append_to_file",
                            insert="print('dispatch sqrt')\n",
                        ),
                    ]
                ),
                repo_root=root,
                plan={"acceptance_criteria": ["CLI supports sqrt via argparse"]},
            )

            self.assertTrue(any("multiple local insert/append operations" in warning for warning in warnings))

    def test_no_warning_for_full_file_rewrite_in_small_main(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_small_main(root / "main.py", line_count=50)

            warnings = detect_small_file_structural_edit_risk(
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="main.py",
                            change_type="modified",
                            content="import argparse\n\ndef main():\n    pass\n",
                            mode="full_file_rewrite",
                        ),
                    ]
                ),
                repo_root=root,
                plan={"acceptance_criteria": ["CLI supports sqrt via argparse"]},
            )

            self.assertFalse(any("Small file structural edit risk" in warning for warning in warnings))

    def test_no_small_file_warning_for_large_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_small_main(root / "main.py", line_count=130)

            warnings = detect_small_file_structural_edit_risk(
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="main.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="insert_after_line",
                            target="line 10",
                            insert="subparsers.add_parser('sqrt')\n",
                        ),
                        FileChange(
                            path="main.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="append_to_file",
                            insert="print('dispatch sqrt')\n",
                        ),
                    ]
                ),
                repo_root=root,
                plan={"acceptance_criteria": ["CLI supports sqrt via argparse"]},
            )

            self.assertFalse(any("Small file structural edit risk" in warning for warning in warnings))

    def test_warning_for_append_after_main_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text(
                "import argparse\n\n"
                "def main():\n"
                "    parser = argparse.ArgumentParser()\n"
                "    args = parser.parse_args()\n"
                "\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n",
                encoding="utf-8",
            )

            warnings = detect_small_file_structural_edit_risk(
                file_changes=FileChangesOutput(
                    changes=[
                        FileChange(
                            path="main.py",
                            change_type="modified",
                            content=None,
                            mode="operation_based_edit",
                            operation="append_to_file",
                            insert="\ndef sqrt(value):\n    return value ** 0.5\n",
                        ),
                    ]
                ),
                repo_root=root,
                plan={"acceptance_criteria": ["CLI supports sqrt via argparse"]},
            )

            self.assertTrue(any("after an if __name__" in warning for warning in warnings))


class SmallFilePolicyCliTests(unittest.TestCase):
    def test_diff_warnings_include_small_file_risk(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text(
                "import argparse\n\n"
                "def main():\n"
                "    parser = argparse.ArgumentParser()\n"
                "    subparsers = parser.add_subparsers(dest='command')\n"
                "    args = parser.parse_args()\n"
                "\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n",
                encoding="utf-8",
            )
            session = _create_diff_session(root)
            provider = _FakeProvider(
                """
{
  "changes": [
    {
      "path": "main.py",
      "change_type": "modified",
      "mode": "operation_based_edit",
      "operation": "insert_after_line",
      "target": "    subparsers = parser.add_subparsers(dest='command')",
      "insert": "    sqrt_parser = subparsers.add_parser('sqrt')\\n"
    },
    {
      "path": "main.py",
      "change_type": "modified",
      "mode": "operation_based_edit",
      "operation": "append_to_file",
      "insert": "\\ndef sqrt(value):\\n    return value ** 0.5\\n"
    }
  ]
}
"""
            )

            with patch("trevvos_forge.cli.build_provider", return_value=provider):
                result = runner.invoke(app, ["diff", "--path", str(root)])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue((session.path / "diff_warnings.json").exists())

            diff_warnings = json.loads((session.path / "diff_warnings.json").read_text(encoding="utf-8"))
            semantic_review = json.loads((session.path / "semantic_review.json").read_text(encoding="utf-8"))
            change_summary = (session.path / "change_summary.md").read_text(encoding="utf-8")

            self.assertTrue(
                any("Small file structural edit risk" in warning for warning in diff_warnings["warnings"])
            )
            self.assertTrue(
                any("Small file structural edit risk" in warning for warning in semantic_review["warnings"])
            )
            self.assertIn("Small file structural edit risk", change_summary)


def _create_diff_session(root: Path):
    session = create_session(root, "Adicione o comando sqrt em main.py para a CLI usando argparse", command="plan")
    write_session_text(session, "context.md", "Context")
    write_session_text(session, "plan.md", "Plan")
    write_session_json(
        session,
        "plan.json",
        {
            "expected_behavior": ["python main.py sqrt 9 prints 3"],
            "acceptance_criteria": ["CLI supports sqrt via argparse"],
            "suggested_verification_commands": [],
            "files_to_create": [],
            "files_to_modify": ["main.py"],
            "files_not_to_modify": [],
        },
    )
    write_session_json(
        session,
        "selected_files.json",
        {
            "selected_files": [
                {
                    "path": "main.py",
                    "size_bytes": 100,
                    "score": 10,
                    "reason": "test",
                    "is_truncated": False,
                    "included_ranges": [{"start_line": 1, "end_line": 9}],
                    "total_lines": 9,
                    "markdown_headings": [],
                }
            ]
        },
    )
    return session


def _write_small_main(path: Path, *, line_count: int) -> None:
    lines = [
        "import argparse",
        "",
        "def main():",
        "    parser = argparse.ArgumentParser()",
        "    subparsers = parser.add_subparsers(dest='command')",
        "    args = parser.parse_args()",
        "",
        "if __name__ == \"__main__\":",
        "    main()",
    ]
    lines.extend(f"# filler {index}" for index in range(max(0, line_count - len(lines))))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


if __name__ == "__main__":
    unittest.main()
