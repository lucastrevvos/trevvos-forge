import unittest

from trevvos_forge.test_structure_validation import (
    repair_missing_test_imports,
    repair_unittest_method_indentation,
    validate_generated_test_structure,
)


class TestStructureValidationTests(unittest.TestCase):
    def test_blocks_top_level_pytest_function_in_unittest(self) -> None:
        result = validate_generated_test_structure(
            content=(
                "import unittest\n\n"
                "class TestCalculator(unittest.TestCase):\n"
                "    def test_divide(self):\n"
                "        self.assertEqual(4 / 2, 2)\n\n"
                "def test_add_positive_numbers():\n"
                "    assert add(1, 2) == 3\n"
            ),
            framework="unittest",
            test_file="tests/test_calculator.py",
            source_symbols=["add", "divide"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(
            any("Top-level pytest-style test function" in error for error in result["errors"]),
            result["errors"],
        )

    def test_blocks_self_assert_outside_testcase(self) -> None:
        result = validate_generated_test_structure(
            content="def test_add_positive_numbers():\n    self.assertEqual(add(1, 2), 3)\n",
            framework="pytest",
            test_file="tests/test_calculator.py",
            source_symbols=["add"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("uses self.assert*" in error for error in result["errors"]), result["errors"])

    def test_blocks_nested_test_functions(self) -> None:
        result = validate_generated_test_structure(
            content=(
                "from calculator import add\n\n"
                "def test_add_positive_numbers():\n"
                "    def test_add_negative_numbers():\n"
                "        assert add(-1, -2) == -3\n"
            ),
            framework="pytest",
            test_file="tests/test_calculator.py",
            source_symbols=["add"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("Nested test function `test_add_negative_numbers`" in error for error in result["errors"]))

    def test_blocks_source_symbol_used_without_import(self) -> None:
        result = validate_generated_test_structure(
            content=(
                "import unittest\n"
                "from calculator import divide\n\n"
                "class TestCalculator(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(1, 2), 3)\n"
            ),
            framework="unittest",
            test_file="tests/test_calculator.py",
            source_symbols=["add", "divide"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("Symbol `add` is used but not imported or defined.", result["errors"])

    def test_allows_correct_unittest_structure(self) -> None:
        result = validate_generated_test_structure(
            content=(
                "import unittest\n"
                "from calculator import add, divide\n\n"
                "class TestCalculator(unittest.TestCase):\n"
                "    def test_add_positive_numbers(self):\n"
                "        self.assertEqual(add(1, 2), 3)\n\n"
                "    def test_divide_by_zero_raises_value_error(self):\n"
                "        with self.assertRaises(ValueError):\n"
                "            divide(10, 0)\n"
            ),
            framework="unittest",
            test_file="tests/test_calculator.py",
            source_symbols=["add", "divide"],
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            result["discovered_tests"],
            [
                "TestCalculator.test_add_positive_numbers",
                "TestCalculator.test_divide_by_zero_raises_value_error",
            ],
        )

    def test_allows_correct_pytest_structure(self) -> None:
        result = validate_generated_test_structure(
            content=(
                "import pytest\n"
                "from calculator import add, divide\n\n"
                "def test_add_positive_numbers():\n"
                "    assert add(1, 2) == 3\n\n"
                "def test_divide_by_zero_raises_value_error():\n"
                "    with pytest.raises(ValueError):\n"
                "        divide(10, 0)\n"
            ),
            framework="pytest",
            test_file="tests/test_calculator.py",
            source_symbols=["add", "divide"],
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            result["discovered_tests"],
            ["test_add_positive_numbers", "test_divide_by_zero_raises_value_error"],
        )

    def test_repairs_existing_import_line(self) -> None:
        result = repair_missing_test_imports(
            content=(
                "import unittest\n"
                "from calculator import divide\n\n"
                "class TestCalculator(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(1, 2), 3)\n"
                "    def test_subtract(self):\n"
                "        self.assertEqual(subtract(5, 2), 3)\n"
            ),
            test_file="tests/test_calculator.py",
            source_module="calculator",
            missing_symbols=["add", "subtract"],
            source_symbols=["add", "subtract", "divide"],
        )

        self.assertEqual(result["status"], "repaired")
        self.assertEqual(result["symbols_added"], ["add", "subtract"])
        self.assertIn("from calculator import add, divide, subtract", result["content"])

    def test_repairs_new_import_when_missing(self) -> None:
        result = repair_missing_test_imports(
            content=(
                "import unittest\n\n"
                "class TestCalculator(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(1, 2), 3)\n"
            ),
            test_file="tests/test_calculator.py",
            source_module="calculator",
            missing_symbols=["add", "subtract"],
            source_symbols=["add", "subtract"],
        )

        self.assertEqual(result["status"], "repaired")
        self.assertIn("from calculator import add, subtract", result["content"])
        self.assertIn("import unittest\nfrom calculator import add, subtract\n\nclass TestCalculator", result["content"])

    def test_does_not_repair_symbols_outside_source(self) -> None:
        result = repair_missing_test_imports(
            content="import unittest\n",
            test_file="tests/test_calculator.py",
            source_module="calculator",
            missing_symbols=["foo"],
            source_symbols=["add", "subtract"],
        )

        self.assertEqual(result["status"], "not_repairable")
        self.assertEqual(result["reason"], "missing_symbol_not_in_source")

    def test_repairs_unittest_method_indentation_from_append_block(self) -> None:
        result = repair_unittest_method_indentation(
            content=(
                "\n\n        def test_power_negative_exponent(self):\n"
                "            self.assertAlmostEqual(power(2, -3), 0.125)\n\n"
                "        def test_power_zero_exponent(self):\n"
                "            self.assertEqual(power(2, 0), 1)\n"
                "    def test_power_positive_exponent(self):\n"
                "        self.assertEqual(power(2, 3), 8)\n"
            ),
            test_file="tests/test_calculator.py",
        )

        self.assertEqual(result["status"], "repaired")
        self.assertEqual(result["strategy"], "normalize_unittest_method_indentation")
        self.assertEqual(
            result["methods_repaired"],
            [
                "test_power_negative_exponent",
                "test_power_zero_exponent",
                "test_power_positive_exponent",
            ],
        )
        self.assertIn("    def test_power_negative_exponent(self):", result["content"])
        self.assertIn("        self.assertAlmostEqual(power(2, -3), 0.125)", result["content"])
        self.assertIn("    def test_power_positive_exponent(self):", result["content"])

    def test_does_not_repair_complex_unittest_insert(self) -> None:
        result = repair_unittest_method_indentation(
            content=(
                "import unittest\n\n"
                "        def test_power(self):\n"
                "            self.assertEqual(power(2, 3), 8)\n"
            ),
            test_file="tests/test_calculator.py",
        )

        self.assertEqual(result["status"], "not_repairable")
        self.assertEqual(result["reason"], "complex_nested_structure")


if __name__ == "__main__":
    unittest.main()
