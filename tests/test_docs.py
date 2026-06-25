import unittest
from pathlib import Path
import re

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

        self.assertRegex(readme, r"\|\s*Command\s*\|\s*Mode\s*\|\s*Modifies code\?\s*\|\s*Purpose\s*\|",)
        self.assertRegex(readme, r"\|\s*`trevvos apply`\s*\|\s*Execution\s*\|\s*Yes\s*\|",)
        self.assertRegex(readme, r"\|\s*`trevvos review-diff`\s*\|\s*Advisory\s*\|\s*No\s*\|",)

    def test_readme_and_docs_show_cd_example_for_project_root(self) -> None:
        readme = _read("README.md").lower()
        advisory = _read("docs/advisory-mode.md").lower()

        self.assertIn("cd path/to/your/project", readme)
        self.assertIn("cd path/to/your/project", advisory)

    # -----------------------------------------------------------------------
    # Marco 81: new docs and content
    # -----------------------------------------------------------------------

    def test_readme_mentions_controlled_testing_and_setup(self) -> None:
        readme = _read("README.md")

        self.assertIn("Controlled Testing Mode", readme)
        self.assertIn("trevvos setup", readme)
        self.assertIn("openai-compatible", readme)
        self.assertIn("trevvos api start --open", readme)

    def test_new_docs_exist(self) -> None:
        self.assertTrue((ROOT / "docs" / "alpha-quickstart.md").exists())
        self.assertTrue((ROOT / "docs" / "providers.md").exists())
        self.assertTrue((ROOT / "docs" / "controlled-testing-mode.md").exists())
        self.assertTrue((ROOT / "docs" / "local-api-dashboard.md").exists())
        self.assertTrue((ROOT / "docs" / "troubleshooting.md").exists())

    def test_controlled_testing_docs_cover_full_flow(self) -> None:
        text = _read("docs/controlled-testing-mode.md").lower()

        self.assertIn("sandbox", text)
        self.assertIn("tests add", text)
        self.assertIn("tests apply", text)
        self.assertIn("tests inspect", text)
        self.assertIn("does not modify", text)
        self.assertIn("git apply", text)

    def test_providers_docs_cover_ollama_and_openai_compatible(self) -> None:
        text = _read("docs/providers.md").lower()

        self.assertIn("ollama", text)
        self.assertIn("openai-compatible", text)
        self.assertIn("api_key", text)
        self.assertIn("trevvos_forge_api_key", text)
        self.assertIn("lm studio", text)

    def test_troubleshooting_docs_cover_key_topics(self) -> None:
        text = _read("docs/troubleshooting.md").lower()

        self.assertIn("trevvos doctor", text)
        self.assertIn("ollama", text)
        self.assertIn("openai-compatible", text)
        self.assertIn("trevvos tests apply", text)

    def test_alpha_quickstart_covers_both_providers(self) -> None:
        text = _read("docs/alpha-quickstart.md").lower()

        self.assertIn("ollama", text)
        self.assertIn("openai-compatible", text)
        self.assertIn("trevvos setup", text)
        self.assertIn("trevvos doctor", text)
        self.assertIn("trevvos tests add", text)

    # -----------------------------------------------------------------------
    # Marco 82: Alpha release docs
    # -----------------------------------------------------------------------

    def test_alpha_docs_exist(self) -> None:
        self.assertTrue((ROOT / "ALPHA.md").exists())
        self.assertTrue((ROOT / "docs" / "alpha-test-plan.md").exists())
        self.assertTrue((ROOT / "docs" / "feedback-template.md").exists())
        self.assertTrue((ROOT / "docs" / "known-limitations.md").exists())
        self.assertTrue((ROOT / "docs" / "alpha-safety.md").exists())
        self.assertTrue((ROOT / "docs" / "release-checklist.md").exists())

    def test_readme_links_to_alpha(self) -> None:
        readme = _read("README.md")

        self.assertIn("ALPHA.md", readme)

    def test_alpha_md_mentions_setup_and_key_commands(self) -> None:
        text = _read("ALPHA.md").lower()

        self.assertIn("trevvos setup", text)
        self.assertIn("trevvos doctor", text)
        self.assertIn("trevvos sessions export", text)
        self.assertIn("advisory", text)
        self.assertIn("controlled testing", text)

    def test_feedback_template_mentions_session_export(self) -> None:
        text = _read("docs/feedback-template.md").lower()

        self.assertIn("trevvos sessions export", text)
        self.assertIn("environment", text)
        self.assertIn("provider", text)

    def test_known_limitations_mentions_experimental_execution(self) -> None:
        text = _read("docs/known-limitations.md").lower()

        self.assertIn("experimental", text)
        self.assertIn("trevvos apply", text)
        self.assertIn("trevvos plan", text)
        self.assertIn("not recommended", text)

    def test_alpha_safety_covers_advisory_and_controlled_testing(self) -> None:
        text = _read("docs/alpha-safety.md").lower()

        self.assertIn("read-only", text)
        self.assertIn("sandbox", text)
        self.assertIn("test files only", text)
        self.assertIn("api_key", text)
        self.assertIn("127.0.0.1", text)


    # -----------------------------------------------------------------------
    # Marco 84: GitHub Release v0.1.0-alpha.1 docs
    # -----------------------------------------------------------------------

    def test_release_notes_exist(self) -> None:
        self.assertTrue((ROOT / "RELEASE_NOTES.md").exists())

    def test_release_notes_content(self) -> None:
        text = _read("RELEASE_NOTES.md").lower()

        self.assertIn("v0.1.0-alpha.1", text)
        self.assertIn("windows-x64.zip", text)
        self.assertIn("linux-x64.tar.gz", text)
        self.assertIn("sha256sums", text)
        self.assertIn("trevvos setup", text)
        self.assertIn("trevvos sessions export", text)

    def test_release_specific_doc_exists(self) -> None:
        self.assertTrue((ROOT / "docs" / "release-v0.1.0-alpha.1.md").exists())

    def test_alpha_download_install_doc_exists(self) -> None:
        self.assertTrue((ROOT / "docs" / "alpha-download-install.md").exists())

    def test_readme_links_to_download_install(self) -> None:
        readme = _read("README.md")
        self.assertIn("docs/alpha-download-install.md", readme)

    def test_alpha_md_links_to_download_install(self) -> None:
        text = _read("ALPHA.md")
        self.assertIn("docs/alpha-download-install.md", text)

    def test_release_checklist_mentions_github_release_assets(self) -> None:
        text = _read("docs/release-checklist.md").lower()
        self.assertIn("windows zip", text)
        self.assertIn("linux", text)
        self.assertIn("sha256sums", text)
        self.assertIn("pre-release", text)

    def test_issue_template_exists(self) -> None:
        self.assertTrue(
            (ROOT / ".github" / "ISSUE_TEMPLATE" / "alpha-feedback.md").exists()
        )

    def test_download_install_guide_covers_windows_and_linux(self) -> None:
        text = _read("docs/alpha-download-install.md").lower()
        self.assertIn("windows", text)
        self.assertIn("linux", text)
        self.assertIn("trevvos setup", text)
        self.assertIn("trevvos sessions export", text)


    # -----------------------------------------------------------------------
    # Marco 85: Closed Alpha Test Run docs
    # -----------------------------------------------------------------------

    def test_alpha_run_docs_exist(self) -> None:
        self.assertTrue((ROOT / "docs" / "alpha-tester-invite.md").exists())
        self.assertTrue((ROOT / "docs" / "alpha-runbook.md").exists())
        self.assertTrue((ROOT / "docs" / "alpha-feedback-triage.md").exists())
        self.assertTrue((ROOT / "docs" / "alpha-success-criteria.md").exists())
        self.assertTrue((ROOT / "docs" / "alpha-known-issues.md").exists())
        self.assertTrue((ROOT / "docs" / "alpha-results-template.md").exists())

    def test_alpha_md_links_to_runbook(self) -> None:
        text = _read("ALPHA.md")
        self.assertIn("docs/alpha-runbook.md", text)

    def test_readme_links_to_tester_invite(self) -> None:
        text = _read("README.md")
        self.assertIn("docs/alpha-tester-invite.md", text)

    def test_readme_links_to_success_criteria(self) -> None:
        text = _read("README.md")
        self.assertIn("docs/alpha-success-criteria.md", text)

    def test_alpha_invite_covers_key_commands(self) -> None:
        text = _read("docs/alpha-tester-invite.md").lower()
        self.assertIn("trevvos setup", text)
        self.assertIn("trevvos doctor", text)
        self.assertIn("trevvos sessions export", text)
        self.assertIn("execution mode", text)

    def test_alpha_success_criteria_has_safety_requirement(self) -> None:
        text = _read("docs/alpha-success-criteria.md").lower()
        self.assertIn("no critical safety issue", text)
        self.assertIn("advisory mode", text)
        self.assertIn("pause", text)

    def test_alpha_triage_has_severity_labels(self) -> None:
        text = _read("docs/alpha-feedback-triage.md").lower()
        self.assertIn("critical", text)
        self.assertIn("high", text)
        self.assertIn("medium", text)
        self.assertIn("low", text)
        self.assertIn("severity", text)

    def test_alpha_known_issues_mentions_execution_mode(self) -> None:
        text = _read("docs/alpha-known-issues.md").lower()
        self.assertIn("execution mode", text)
        self.assertIn("experimental", text)

    def test_issue_template_has_severity_and_artifact(self) -> None:
        text = _read(".github/ISSUE_TEMPLATE/alpha-feedback.md").lower()
        self.assertIn("severity", text)
        self.assertIn("artifact used", text)
        self.assertIn("trevvos sessions export", text)

    def test_release_checklist_has_alpha_launch_section(self) -> None:
        text = _read("docs/release-checklist.md").lower()
        self.assertIn("closed alpha launch", text)
        self.assertIn("alpha-tester-invite", text)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
