import unittest

from trevvos_forge.verification_coverage import (
    check_plan_verification_coverage,
    extract_command_like_expected_behaviors,
)


class VerificationCoverageTests(unittest.TestCase):
    def test_coverage_passes_when_expected_command_is_suggested(self) -> None:
        result = check_plan_verification_coverage(
            {
                "expected_behavior": ["python main.py sqrt 9 prints 3.0"],
                "suggested_verification_commands": [
                    "python -m py_compile calculator.py main.py",
                    "python main.py sqrt 9",
                ],
            }
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["covered"], ["python main.py sqrt 9"])
        self.assertEqual(result["missing"], [])

    def test_coverage_fails_when_expected_command_is_not_suggested(self) -> None:
        result = check_plan_verification_coverage(
            {
                "expected_behavior": ["python main.py sqrt 9 prints 3.0"],
                "suggested_verification_commands": [
                    "python -m py_compile calculator.py main.py",
                ],
            }
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["missing"], ["python main.py sqrt 9"])
        self.assertIn("python main.py sqrt 9", result["warnings"][0])

    def test_extracts_backtick_command(self) -> None:
        commands = extract_command_like_expected_behaviors(
            {"expected_behavior": ["`python main.py sqrt 9` should print 3.0"]}
        )

        self.assertEqual(commands, ["python main.py sqrt 9"])


if __name__ == "__main__":
    unittest.main()
