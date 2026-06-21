import unittest
import tempfile
from pathlib import Path

from trevvos_forge.context_builder import (
    build_context,
    content_with_line_numbers,
    extract_markdown_headings,
)


class ContextEnrichmentTests(unittest.TestCase):
    def test_extract_markdown_headings(self) -> None:
        content = """# Trevvos Forge

Intro.

## Usage

Text.
"""

        headings = extract_markdown_headings(content)

        self.assertEqual(
            [
                {"line": heading.line, "level": heading.level, "text": heading.text}
                for heading in headings
            ],
            [
                {"line": 1, "level": 1, "text": "Trevvos Forge"},
                {"line": 5, "level": 2, "text": "Usage"},
            ],
        )

    def test_content_with_line_numbers(self) -> None:
        self.assertEqual(
            content_with_line_numbers("a\nb\nc"),
            "1 | a\n2 | b\n3 | c",
        )

    def test_built_context_includes_editorial_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "README.md").write_text(
                "# Trevvos Forge\n\nIntro text.\n\n## Usage\n\n"
                + "\n".join(f"Text {index}." for index in range(30))
                + "\n",
                encoding="utf-8",
            )

            built_context = build_context(
                root=root,
                instruction="update README",
                max_files=1,
                max_total_chars=80,
                max_chars_per_file=80,
            )
            context_markdown = built_context.to_markdown()

            self.assertIn("Content with line numbers", context_markdown)
            self.assertIn("1 | # Trevvos Forge", context_markdown)
            self.assertIn('"text": "Trevvos Forge"', context_markdown)
            self.assertIn("Truncated: true", context_markdown)
            self.assertIn('"start_line": 1', context_markdown)


if __name__ == "__main__":
    unittest.main()
