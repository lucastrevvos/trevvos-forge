import unittest

from trevvos_forge.prompt_catalog import get_prompt


class FileChangesPromptTests(unittest.TestCase):
    def test_prompt_contains_markdown_editing_rules(self) -> None:
        prompt = get_prompt("file_changes_generation").render(
            workspace_context="context",
            plan="plan",
            instruction="instruction",
        )

        self.assertIn("Preserve integralmente o conteudo existente", prompt)
        self.assertIn("Nao concatene o texto novo em um paragrafo existente", prompt)
        self.assertIn("abaixo do titulo principal", prompt)
        self.assertIn("Nao copie numeros de linha", prompt)
        self.assertIn("insert_before_line", prompt)
        self.assertIn("replace_block", prompt)
        self.assertIn("append_to_file", prompt)

    def test_semantic_patch_review_prompt_contains_safety_rules(self) -> None:
        prompt = get_prompt("semantic_patch_review").render(
            review_context="{}",
        )

        self.assertIn("informational only", prompt)
        self.assertIn("does not prove semantic correctness", prompt)
        self.assertIn("Do not invent files", prompt)
        self.assertIn("Consider warnings", prompt)
        self.assertIn("Return ONLY valid JSON", prompt)

    def test_file_changes_retry_prompt_contains_repair_rules(self) -> None:
        prompt = get_prompt("file_changes_retry").render(
            retry_context="retry context",
        )

        self.assertIn("Do not repeat invalid target", prompt)
        self.assertIn("target_not_found", prompt)
        self.assertIn("ambiguous_target", prompt)
        self.assertIn("full_file_rewrite", prompt)
        self.assertIn('"changes"', prompt)
        self.assertIn("retry context", prompt)

    def test_commit_message_prompt_contains_safety_rules(self) -> None:
        prompt = get_prompt("commit_message_generation").render(
            commit_context="{}",
        )

        self.assertIn("Return ONLY valid JSON", prompt)
        self.assertIn("Do not invent scope", prompt)
        self.assertIn("subject", prompt)
        self.assertIn("72 characters", prompt)


if __name__ == "__main__":
    unittest.main()
