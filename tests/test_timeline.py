import json
import tempfile
import unittest
from pathlib import Path

from trevvos_forge.timeline import (
    append_timeline_event,
    read_timeline,
    render_timeline_markdown,
    write_timeline_markdown,
)


class TimelineTests(unittest.TestCase):
    def test_append_event_creates_jsonl_with_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)

            append_timeline_event(
                session_dir,
                {
                    "event": "plan_started",
                    "command": "trevvos plan",
                    "status": "started",
                    "artifacts": ["prompt.md"],
                },
            )

            timeline_path = session_dir / "timeline.jsonl"
            self.assertTrue(timeline_path.exists())

            payload = json.loads(timeline_path.read_text(encoding="utf-8").strip())
            self.assertEqual(payload["event"], "plan_started")
            self.assertEqual(payload["status"], "started")
            self.assertEqual(payload["artifacts"], ["prompt.md"])
            self.assertIn("timestamp", payload)

    def test_read_timeline_returns_events_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)

            append_timeline_event(session_dir, {"event": "plan_started", "command": "trevvos plan"})
            append_timeline_event(session_dir, {"event": "plan_completed", "command": "trevvos plan"})

            events = read_timeline(session_dir)

            self.assertEqual([event["event"] for event in events], ["plan_started", "plan_completed"])

    def test_render_markdown_contains_event_status_and_reason(self) -> None:
        markdown = render_timeline_markdown(
            [
                {
                    "timestamp": "2026-06-22T10:30:00-03:00",
                    "event": "diff_failed",
                    "status": "failed",
                    "reason": "invalid_file_changes_schema",
                }
            ]
        )

        self.assertIn("diff_failed", markdown)
        self.assertIn("failed", markdown)
        self.assertIn("invalid_file_changes_schema", markdown)

    def test_session_without_timeline_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            self.assertEqual(read_timeline(Path(temporary_directory)), [])

    def test_write_timeline_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            append_timeline_event(session_dir, {"event": "repair_not_repairable", "status": "not_repairable"})

            write_timeline_markdown(session_dir)

            self.assertTrue((session_dir / "timeline.md").exists())
            self.assertIn("repair_not_repairable", (session_dir / "timeline.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
