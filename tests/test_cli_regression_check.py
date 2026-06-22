import unittest

from trevvos_forge.cli_regression_check import (
    check_cli_command_preservation,
    extract_argparse_subcommands,
    extract_dispatch_commands,
)


class CliRegressionCheckTests(unittest.TestCase):
    def test_extracts_argparse_subcommands(self) -> None:
        content = """
subparsers.add_parser("add")
subparsers.add_parser('divide')
"""

        self.assertEqual(extract_argparse_subcommands(content), ["add", "divide"])

    def test_extracts_dispatch_commands(self) -> None:
        content = """
if args.command == "add":
    print(add(args.a, args.b))
elif args.command == 'divide':
    print(divide(args.a, args.b))
"""

        self.assertEqual(extract_dispatch_commands(content), ["add", "divide"])

    def test_detects_removed_command(self) -> None:
        original = """
subparsers.add_parser("add")
subparsers.add_parser("divide")
if args.command == "add":
    pass
elif args.command == "divide":
    pass
"""
        new = """
subparsers.add_parser("add")
subparsers.add_parser("sqrt")
if args.command == "add":
    pass
elif args.command == "sqrt":
    pass
"""

        result = check_cli_command_preservation(original, new, "main.py")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["removed_subcommands"], ["divide"])
        self.assertEqual(result["removed_dispatch_commands"], ["divide"])

    def test_passes_when_command_is_added_without_removing_existing(self) -> None:
        original = """
subparsers.add_parser("add")
subparsers.add_parser("divide")
if args.command == "add":
    pass
elif args.command == "divide":
    pass
"""
        new = """
subparsers.add_parser("add")
subparsers.add_parser("divide")
subparsers.add_parser("sqrt")
if args.command == "add":
    pass
elif args.command == "divide":
    pass
elif args.command == "sqrt":
    pass
"""

        result = check_cli_command_preservation(original, new, "main.py")

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["added_subcommands"], ["sqrt"])
        self.assertEqual(result["added_dispatch_commands"], ["sqrt"])


if __name__ == "__main__":
    unittest.main()
