import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_readme_mentions_advisory_mode_and_commands(self) -> None:
        readme = _read("README.md")

        self.assertIn("Advisory Mode", readme)
        self.assertIn("Execution Mode", readme)
        self.assertIn("current working directory", readme)
        self.assertIn("--target", readme)
        self.assertIn("language", readme)
        self.assertIn("trevvos inspect", readme)
        self.assertIn("trevvos analyze", readme)
        self.assertIn("trevvos explain", readme)
        self.assertIn("trevvos propose", readme)
        self.assertIn("trevvos spec", readme)
        self.assertIn("trevvos review-diff", readme)

    def test_docs_exist(self) -> None:
        self.assertTrue((ROOT / "docs" / "advisory-mode.md").exists())
        self.assertTrue((ROOT / "docs" / "execution-mode.md").exists())
        self.assertTrue((ROOT / "docs" / "safety-model.md").exists())

    def test_advisory_docs_do_not_promise_automatic_editing(self) -> None:
        text = _read("docs/advisory-mode.md").lower()

        self.assertIn("recommended", text)
        self.assertIn("does not modify code", text)
        self.assertIn("no patches", text)
        self.assertIn("current working directory", text)
        self.assertIn("project root", text)
        self.assertIn("response language", text)

    def test_execution_docs_mark_experimental_and_apply_safety(self) -> None:
        text = _read("docs/execution-mode.md").lower()

        self.assertIn("experimental", text)
        self.assertIn("review generated diffs", text)
        self.assertIn("confirmation before apply", text)
        self.assertIn("current working directory", text)
        self.assertIn("project root", text)
        self.assertIn("language", text)

    def test_safety_docs_mention_local_first_sessions_sandbox_and_git_check(self) -> None:
        text = _read("docs/safety-model.md").lower()

        self.assertIn("local-first", text)
        self.assertIn("sessions", text)
        self.assertIn("artifacts", text)
        self.assertIn("sandbox", text)
        self.assertIn("confirmation", text)
        self.assertIn("git apply --check", text)

    def test_readme_commands_table_has_modifies_code_column(self) -> None:
        readme = _read("README.md")

        self.assertIn("| Command | Mode | Modifies code? | Purpose |", readme)
        self.assertIn("| `trevvos apply` | Execution | Yes |", readme)
        self.assertIn("| `trevvos review-diff` | Advisory | No |", readme)

    def test_readme_and_docs_show_cd_example_for_project_root(self) -> None:
        readme = _read("README.md").lower()
        advisory = _read("docs/advisory-mode.md").lower()

        self.assertIn("cd path/to/your/project", readme)
        self.assertIn("cd path/to/your/project", advisory)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
