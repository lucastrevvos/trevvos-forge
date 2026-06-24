"""RetryBudget — tracks retry attempts and status for a single retry type."""
from __future__ import annotations

from dataclasses import dataclass


class RetryBudgetExhausted(Exception):
    pass


@dataclass
class RetryBudget:
    """Tracks a single retry budget with attempt counting and status lifecycle.

    Supports read-only dict-style access (``budget["used"]``, ``budget.get("max")``)
    so it can be passed directly to legacy functions that call ``.get()`` on retry dicts.
    """

    max: int
    used: int = 0
    status: str = "not_needed"

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def can_retry(self) -> bool:
        return self.used < self.max

    def consume(self) -> int:
        """Increment used count and return the 1-based attempt number.

        Raises RetryBudgetExhausted if the budget is already exhausted.
        """
        if not self.can_retry():
            raise RetryBudgetExhausted(
                f"Retry budget exhausted: used={self.used}, max={self.max}"
            )
        self.used += 1
        return self.used

    def mark_not_needed(self) -> None:
        self.status = "not_needed"

    def mark_succeeded_after_retry(self) -> None:
        self.status = "succeeded_after_retry"

    def mark_failed_after_retries(self) -> None:
        self.status = "failed_after_retries"

    def mark_disabled(self) -> None:
        self.status = "disabled"

    def to_dict(self) -> dict:
        return {"max": self.max, "used": self.used, "status": self.status}

    # ------------------------------------------------------------------
    # Dict-compatible read access (for legacy helper functions)
    # ------------------------------------------------------------------

    def __getitem__(self, key: str) -> object:
        return self.to_dict()[key]

    def get(self, key: str, default: object = None) -> object:
        return self.to_dict().get(key, default)
