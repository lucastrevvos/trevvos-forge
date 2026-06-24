"""Unit tests for ProgressReporter."""
import unittest
from unittest.mock import MagicMock, call

from trevvos_forge.progress_reporter import (
    NoopProgressReporter,
    RichProgressReporter,
    build_progress_reporter,
)


class TestNoopProgressReporter(unittest.TestCase):
    def test_start_stage_does_not_raise(self) -> None:
        reporter = NoopProgressReporter()
        reporter.start_stage("Doing something...")

    def test_finish_stage_does_not_raise(self) -> None:
        reporter = NoopProgressReporter()
        reporter.finish_stage()

    def test_fail_stage_does_not_raise(self) -> None:
        reporter = NoopProgressReporter()
        reporter.fail_stage()

    def test_context_manager_returns_self(self) -> None:
        reporter = NoopProgressReporter()
        with reporter as r:
            self.assertIs(r, reporter)

    def test_context_manager_enter_exit_no_raise(self) -> None:
        reporter = NoopProgressReporter()
        with reporter:
            reporter.start_stage("Stage A")
            reporter.finish_stage()

    def test_all_methods_callable_multiple_times(self) -> None:
        reporter = NoopProgressReporter()
        for label in ["Stage 1", "Stage 2", "Stage 3"]:
            reporter.start_stage(label)
            reporter.finish_stage()


class TestRichProgressReporter(unittest.TestCase):
    def _make_console(self) -> MagicMock:
        status_ctx = MagicMock()
        status_ctx.__enter__ = MagicMock(return_value=status_ctx)
        status_ctx.__exit__ = MagicMock(return_value=False)
        console = MagicMock()
        console.status = MagicMock(return_value=status_ctx)
        return console

    def test_enter_starts_status(self) -> None:
        console = self._make_console()
        reporter = RichProgressReporter(console)
        with reporter:
            console.status.assert_called_once()
            console.status.return_value.__enter__.assert_called_once()

    def test_exit_stops_status(self) -> None:
        console = self._make_console()
        reporter = RichProgressReporter(console)
        with reporter:
            pass
        console.status.return_value.__exit__.assert_called_once()

    def test_start_stage_updates_status(self) -> None:
        console = self._make_console()
        reporter = RichProgressReporter(console)
        with reporter:
            reporter.start_stage("Generating tests...")
            console.status.return_value.update.assert_called_once_with("[bold]Generating tests...[/bold]")

    def test_multiple_stages_update_in_order(self) -> None:
        console = self._make_console()
        reporter = RichProgressReporter(console)
        with reporter:
            reporter.start_stage("Stage A")
            reporter.start_stage("Stage B")
        expected_calls = [
            call("[bold]Stage A[/bold]"),
            call("[bold]Stage B[/bold]"),
        ]
        console.status.return_value.update.assert_has_calls(expected_calls)

    def test_start_stage_before_enter_is_noop(self) -> None:
        console = self._make_console()
        reporter = RichProgressReporter(console)
        reporter.start_stage("Should do nothing")
        console.status.return_value.update.assert_not_called()

    def test_finish_stage_does_not_raise(self) -> None:
        console = self._make_console()
        reporter = RichProgressReporter(console)
        with reporter:
            reporter.finish_stage()

    def test_fail_stage_does_not_raise(self) -> None:
        console = self._make_console()
        reporter = RichProgressReporter(console)
        with reporter:
            reporter.fail_stage()

    def test_context_manager_returns_self(self) -> None:
        console = self._make_console()
        reporter = RichProgressReporter(console)
        with reporter as r:
            self.assertIs(r, reporter)


class TestBuildProgressReporter(unittest.TestCase):
    def test_disabled_returns_noop(self) -> None:
        reporter = build_progress_reporter(enabled=False, console=MagicMock())
        self.assertIsInstance(reporter, NoopProgressReporter)

    def test_no_console_returns_noop(self) -> None:
        reporter = build_progress_reporter(enabled=True, console=None)
        self.assertIsInstance(reporter, NoopProgressReporter)

    def test_enabled_with_console_returns_rich(self) -> None:
        reporter = build_progress_reporter(enabled=True, console=MagicMock())
        self.assertIsInstance(reporter, RichProgressReporter)

    def test_enabled_false_ignores_console(self) -> None:
        reporter = build_progress_reporter(enabled=False, console=None)
        self.assertIsInstance(reporter, NoopProgressReporter)

    def test_reporter_is_usable_as_context_manager(self) -> None:
        reporter = build_progress_reporter(enabled=False)
        with reporter:
            reporter.start_stage("Test stage")
