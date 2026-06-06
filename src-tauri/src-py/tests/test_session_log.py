import json
import tempfile
import unittest
from pathlib import Path

from app.utils.session_log import SessionLogStore


class SessionLogStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="gs-session-log-"))
        self.store = SessionLogStore(log_dir=self.temp_dir, source_address="http://127.0.0.1:5000")

    def test_record_command_and_telemetry_persist_to_jsonl(self):
        self.store.record_command("arm", True, message="Vehicle armed successfully")
        self.store.record_telemetry({
            "connected": True,
            "lat": -6.2,
            "lng": 106.8,
            "alt": 12.0,
            "source": "mission-planner",
        })

        self.assertTrue(self.store.path.exists())

        with self.store.path.open("r", encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle if line.strip()]

        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(lines[0]["type"], "session_start")
        self.assertEqual(lines[1]["type"], "command_success")
        self.assertEqual(lines[-1]["type"], "telemetry")

        summary = self.store.summary()
        self.assertEqual(summary["command_count"], 1)
        self.assertEqual(summary["telemetry_count"], 1)
        self.assertEqual(summary["source_address"], "http://127.0.0.1:5000")

    def test_recent_events_respects_limit(self):
        self.store.record_event("note", message="first")
        self.store.record_event("note", message="second")

        recent = self.store.recent_events(limit=1)

        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["message"], "second")


if __name__ == "__main__":
    unittest.main()
