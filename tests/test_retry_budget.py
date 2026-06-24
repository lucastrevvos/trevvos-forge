import unittest

from trevvos_forge.retry_budget import RetryBudget, RetryBudgetExhausted


class RetryBudgetInitTests(unittest.TestCase):
    def test_initial_state(self) -> None:
        budget = RetryBudget(max=2)
        self.assertEqual(budget.max, 2)
        self.assertEqual(budget.used, 0)
        self.assertEqual(budget.status, "not_needed")
        self.assertTrue(budget.can_retry())

    def test_max_zero_cannot_retry(self) -> None:
        budget = RetryBudget(max=0)
        self.assertFalse(budget.can_retry())


class RetryBudgetConsumeTests(unittest.TestCase):
    def test_consume_returns_one_based_attempt(self) -> None:
        budget = RetryBudget(max=3)
        attempt = budget.consume()
        self.assertEqual(attempt, 1)
        self.assertEqual(budget.used, 1)

    def test_consume_increments_sequentially(self) -> None:
        budget = RetryBudget(max=3)
        self.assertEqual(budget.consume(), 1)
        self.assertEqual(budget.consume(), 2)
        self.assertEqual(budget.consume(), 3)
        self.assertEqual(budget.used, 3)

    def test_consume_until_exhausted_then_raises(self) -> None:
        budget = RetryBudget(max=1)
        budget.consume()
        self.assertFalse(budget.can_retry())
        with self.assertRaises(RetryBudgetExhausted):
            budget.consume()

    def test_can_retry_false_after_max_consumed(self) -> None:
        budget = RetryBudget(max=2)
        budget.consume()
        self.assertTrue(budget.can_retry())
        budget.consume()
        self.assertFalse(budget.can_retry())


class RetryBudgetStatusTests(unittest.TestCase):
    def test_mark_not_needed(self) -> None:
        budget = RetryBudget(max=1, status="succeeded_after_retry")
        budget.mark_not_needed()
        self.assertEqual(budget.status, "not_needed")

    def test_mark_succeeded_after_retry(self) -> None:
        budget = RetryBudget(max=1)
        budget.mark_succeeded_after_retry()
        self.assertEqual(budget.status, "succeeded_after_retry")

    def test_mark_failed_after_retries(self) -> None:
        budget = RetryBudget(max=1)
        budget.mark_failed_after_retries()
        self.assertEqual(budget.status, "failed_after_retries")

    def test_mark_disabled(self) -> None:
        budget = RetryBudget(max=0)
        budget.mark_disabled()
        self.assertEqual(budget.status, "disabled")


class RetryBudgetSerializationTests(unittest.TestCase):
    def test_to_dict_shape(self) -> None:
        budget = RetryBudget(max=1)
        self.assertEqual(budget.to_dict(), {"max": 1, "used": 0, "status": "not_needed"})

    def test_to_dict_after_mutations(self) -> None:
        budget = RetryBudget(max=2)
        budget.consume()
        budget.mark_succeeded_after_retry()
        self.assertEqual(budget.to_dict(), {"max": 2, "used": 1, "status": "succeeded_after_retry"})

    def test_getitem_compatibility(self) -> None:
        budget = RetryBudget(max=2, used=1, status="succeeded_after_retry")
        self.assertEqual(budget["max"], 2)
        self.assertEqual(budget["used"], 1)
        self.assertEqual(budget["status"], "succeeded_after_retry")

    def test_get_compatibility(self) -> None:
        budget = RetryBudget(max=1)
        self.assertEqual(budget.get("max"), 1)
        self.assertEqual(budget.get("used"), 0)
        self.assertIsNone(budget.get("nonexistent"))
        self.assertEqual(budget.get("nonexistent", "default"), "default")


if __name__ == "__main__":
    unittest.main()
