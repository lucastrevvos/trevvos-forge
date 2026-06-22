import json
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.project_scanner import (
    build_project_profile_prompt_section,
    load_project_profile,
    render_project_profile,
    save_project_profile,
    scan_project,
)


class ProjectScannerTests(unittest.TestCase):
    def test_detects_python_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text('if __name__ == "__main__":\n    pass\n', encoding="utf-8")
            (root / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

            profile = scan_project(root)

            self.assertIn("python", profile["languages"])
            self.assertIn("main.py", profile["source_files"])
            self.assertIn("calculator.py", profile["source_files"])
            self.assertIn("main.py", profile["entrypoints"])

    def test_detects_python_functions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "calculator.py").write_text(
                "def add(a, b):\n    return a + b\n\n"
                "def divide(a, b):\n    return a / b\n",
                encoding="utf-8",
            )

            profile = scan_project(root)
            functions = profile["python"]["modules"]["calculator.py"]["functions"]

            self.assertIn("add", functions)
            self.assertIn("divide", functions)

    def test_detects_argparse_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "main.py").write_text(
                "subparsers.add_parser(\"add\")\n"
                "subparsers.add_parser(\"divide\")\n",
                encoding="utf-8",
            )

            profile = scan_project(root)
            commands = profile["python"]["modules"]["main.py"]["argparse"]["commands"]

            self.assertEqual(commands, ["add", "divide"])

    def test_detects_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_calculator.py").write_text("import unittest\n", encoding="utf-8")

            profile = scan_project(root)

            self.assertIn("tests", profile["test_directories"])
            self.assertIn("tests/test_calculator.py", profile["test_files"])
            self.assertIn("python -m unittest discover -s tests", profile["suggested_test_commands"])

    def test_detects_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest", "build": "vite build"}}),
                encoding="utf-8",
            )

            profile = scan_project(root)

            self.assertIn("javascript/node", profile["languages"])
            self.assertIn("npm test", profile["suggested_test_commands"])
            self.assertIn("npm run build", profile["suggested_build_commands"])

    def test_detects_dotnet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "Demo.sln").write_text("", encoding="utf-8")
            (root / "Demo.csproj").write_text("<Project />", encoding="utf-8")

            profile = scan_project(root)

            self.assertIn("csharp/dotnet", profile["languages"])
            self.assertIn("dotnet build", profile["suggested_build_commands"])

    def test_ignores_heavy_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            ignored = root / "node_modules"
            ignored.mkdir()
            (ignored / "ignored.py").write_text("def ignored(): pass\n", encoding="utf-8")
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")

            profile = scan_project(root)

            self.assertIn("main.py", profile["source_files"])
            self.assertNotIn("node_modules/ignored.py", profile["source_files"])

    def test_save_and_load_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            profile = {"schema_version": "1.0", "languages": ["python"]}

            path = save_project_profile(root, profile)
            loaded = load_project_profile(root)

            self.assertEqual(path, root / ".trevvos" / "project_profile.json")
            self.assertEqual(loaded, profile)

    def test_render_project_profile(self) -> None:
        text = render_project_profile(
            {
                "summary": "Python project.",
                "languages": ["python"],
                "entrypoints": ["main.py"],
                "source_files": ["main.py"],
                "test_directories": ["tests"],
                "test_files": ["tests/test_main.py"],
                "suggested_test_commands": ["python -m unittest discover -s tests"],
                "suggested_build_commands": [],
            }
        )

        self.assertIn("Languages", text)
        self.assertIn("Entrypoints", text)
        self.assertIn("Suggested test commands", text)
        self.assertIn("Summary", text)

    def test_prompt_section_contains_profile_facts(self) -> None:
        section = build_project_profile_prompt_section(
            {
                "languages": ["python"],
                "entrypoints": ["main.py"],
                "python": {"modules": {"main.py": {"functions": ["main"], "classes": [], "argparse": {"commands": ["add"]}}}},
            }
        )

        self.assertIn("Project profile", section)
        self.assertIn("languages", section)
        self.assertIn("entrypoints", section)
        self.assertIn("main", section)
        self.assertIn("add", section)


if __name__ == "__main__":
    unittest.main()
