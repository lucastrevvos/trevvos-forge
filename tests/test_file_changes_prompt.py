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


if __name__ == "__main__":
    unittest.main()
