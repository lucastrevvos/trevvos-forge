"""Unit tests for ExecutionTracker and CommandTimer."""
import time
import unittest

from trevvos_forge.execution_tracker import CommandTimer, ExecutionStage, ExecutionTracker, format_duration


class TestExecutionTrackerBasics(unittest.TestCase):
    def test_total_duration_is_non_negative(self) -> None:
        tracker = ExecutionTracker()
        self.assertGreaterEqual(tracker.to_dict()["duration_seconds"], 0)

    def test_stages_empty_initially(self) -> None:
        tracker = ExecutionTracker()
        self.assertEqual(tracker.to_dict()["stages"], [])

    def test_start_and_finish_stage(self) -> None:
        tracker = ExecutionTracker()
        tracker.start_stage("prepare", "Preparing context")
        tracker.finish_stage("prepare")
        stages = tracker.to_dict()["stages"]
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["name"], "prepare")
        self.assertEqual(stages[0]["label"], "Preparing context")
        self.assertEqual(stages[0]["status"], "passed")
        self.assertIsNotNone(stages[0]["duration_seconds"])
        self.assertGreaterEqual(stages[0]["duration_seconds"], 0)

    def test_finish_stage_custom_status(self) -> None:
        tracker = ExecutionTracker()
        tracker.start_stage("check", "Checking tests")
        tracker.finish_stage("check", status="skipped")
        stages = tracker.to_dict()["stages"]
        self.assertEqual(stages[0]["status"], "skipped")

    def test_fail_stage_with_error(self) -> None:
        tracker = ExecutionTracker()
        tracker.start_stage("generate", "Generating tests")
        tracker.fail_stage("generate", "schema error")
        stages = tracker.to_dict()["stages"]
        self.assertEqual(stages[0]["status"], "failed")
        self.assertEqual(stages[0]["error"], "schema error")
        self.assertIsNotNone(stages[0]["duration_seconds"])

    def test_fail_stage_without_error_omits_key(self) -> None:
        tracker = ExecutionTracker()
        tracker.start_stage("generate", "Generating tests")
        tracker.fail_stage("generate")
        stages = tracker.to_dict()["stages"]
        self.assertEqual(stages[0]["status"], "failed")
        self.assertNotIn("error", stages[0])

    def test_multiple_stages_preserve_order(self) -> None:
        tracker = ExecutionTracker()
        for name in ["a", "b", "c"]:
            tracker.start_stage(name, f"Stage {name.upper()}")
            tracker.finish_stage(name)
        stages = tracker.to_dict()["stages"]
        self.assertEqual([s["name"] for s in stages], ["a", "b", "c"])

    def test_to_dict_shape(self) -> None:
        tracker = ExecutionTracker()
        tracker.start_stage("s", "S")
        tracker.finish_stage("s")
        data = tracker.to_dict()
        self.assertIn("duration_seconds", data)
        self.assertIn("stages", data)
        stage = data["stages"][0]
        for key in ("name", "label", "status", "duration_seconds"):
            self.assertIn(key, stage)

    def test_total_duration_increases_over_time(self) -> None:
        tracker = ExecutionTracker()
        d1 = tracker.total_duration()
        time.sleep(0.01)
        d2 = tracker.total_duration()
        self.assertGreater(d2, d1)

    def test_running_stage_has_none_duration(self) -> None:
        tracker = ExecutionTracker()
        tracker.start_stage("s", "S")
        stages = tracker.to_dict()["stages"]
        self.assertIsNone(stages[0]["duration_seconds"])
        self.assertEqual(stages[0]["status"], "running")

    def test_duration_seconds_is_float(self) -> None:
        tracker = ExecutionTracker()
        data = tracker.to_dict()
        self.assertIsInstance(data["duration_seconds"], float)

    def test_stage_duration_recorded_independently(self) -> None:
        tracker = ExecutionTracker()
        tracker.start_stage("fast", "Fast stage")
        tracker.finish_stage("fast")
        tracker.start_stage("slow", "Slow stage")
        time.sleep(0.02)
        tracker.finish_stage("slow")
        stages = tracker.to_dict()["stages"]
        fast_dur = stages[0]["duration_seconds"]
        slow_dur = stages[1]["duration_seconds"]
        self.assertGreaterEqual(slow_dur, 0.01)
        self.assertIsNotNone(fast_dur)

    def test_total_duration_covers_all_stages(self) -> None:
        tracker = ExecutionTracker()
        tracker.start_stage("a", "A")
        time.sleep(0.01)
        tracker.finish_stage("a")
        total = tracker.to_dict()["duration_seconds"]
        self.assertGreaterEqual(total, 0.01)

    def test_failed_stage_has_duration(self) -> None:
        tracker = ExecutionTracker()
        tracker.start_stage("s", "S")
        time.sleep(0.005)
        tracker.fail_stage("s", "boom")
        stages = tracker.to_dict()["stages"]
        self.assertGreaterEqual(stages[0]["duration_seconds"], 0)


class TestFormatDuration(unittest.TestCase):
    def test_format_two_decimal_places(self) -> None:
        self.assertEqual(format_duration(1.234), "1.23s")

    def test_format_zero(self) -> None:
        self.assertEqual(format_duration(0.0), "0.00s")

    def test_format_large(self) -> None:
        self.assertEqual(format_duration(120.0), "120.00s")

    def test_format_small(self) -> None:
        self.assertEqual(format_duration(0.005), "0.01s")


class TestCommandTimer(unittest.TestCase):
    def test_duration_seconds_is_non_negative(self) -> None:
        t = CommandTimer()
        self.assertGreaterEqual(t.duration_seconds, 0)

    def test_duration_increases_over_time(self) -> None:
        t = CommandTimer()
        d1 = t.duration_seconds
        time.sleep(0.01)
        d2 = t.duration_seconds
        self.assertGreater(d2, d1)

    def test_format_returns_string_with_s_suffix(self) -> None:
        t = CommandTimer()
        result = t.format()
        self.assertIsInstance(result, str)
        self.assertTrue(result.endswith("s"), result)

    def test_format_has_two_decimal_places(self) -> None:
        t = CommandTimer()
        result = t.format()
        # e.g. "0.00s" — integer part, dot, two digits, 's'
        self.assertRegex(result, r"^\d+\.\d{2}s$")

    def test_to_dict_has_duration_seconds_key(self) -> None:
        t = CommandTimer()
        d = t.to_dict()
        self.assertIn("duration_seconds", d)
        self.assertIsInstance(d["duration_seconds"], float)

    def test_duration_seconds_rounded_to_two(self) -> None:
        t = CommandTimer()
        d = t.duration_seconds
        # Verify it's rounded to 2 decimal places
        self.assertEqual(d, round(d, 2))
