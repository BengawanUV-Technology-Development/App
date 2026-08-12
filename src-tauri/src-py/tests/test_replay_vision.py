import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from jetson.replay_vision import replay


class ReplayVisionTests(unittest.TestCase):
    def test_replay_rewrites_identity_and_sends_overlay_and_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary)
            (session / "epoch.json").write_text(json.dumps({
                "mission_id": "mission-00000000-0000-0000-0000-000000000001",
                "capture_epoch": 1,
            }), encoding="utf-8")
            (session / "frames.jsonl").write_text(
                json.dumps({"frame_id": 4, "capture_monotonic_ns": 1_000_000_000}) + "\n",
                encoding="utf-8",
            )
            (session / "detections.jsonl").write_text(json.dumps({
                "schema_version": "2.0",
                "type": "vision.frame_result",
                "mission_id": "mission-00000000-0000-0000-0000-000000000001",
                "capture_epoch": 1,
                "frame_id": 4,
                "camera_id": "arducam",
                "detections": [{
                    "detection_id": "detection-4",
                    "class": "car",
                    "confidence": 0.9,
                    "bbox_normalized_xyxy": [0.1, 0.2, 0.3, 0.4],
                }],
            }) + "\n", encoding="utf-8")

            args = Namespace(
                session_dir=session,
                overlay_url="http://ground/overlay",
                event_url="http://ground/event",
                token="token",
                delay_ms=0,
                start_delay_ms=0,
                speed=1000,
                fps=30,
                start_frame=0,
                end_frame=None,
                mission_id="mission-00000000-0000-0000-000000000002",
                capture_epoch=2,
                timeout=1,
                dry_run=False,
            )
            posted = []
            with patch("jetson.replay_vision._post", side_effect=lambda *item: posted.append(item)):
                stats = replay(args)

            self.assertEqual(stats, {"rows_selected": 1, "overlay_sent": 1, "events_sent": 1})
            self.assertEqual(posted[0][0], "http://ground/overlay")
            self.assertEqual(posted[0][2]["mission_id"], args.mission_id)
            self.assertEqual(posted[0][2]["capture_epoch"], 2)
            self.assertEqual(posted[0][2]["frame_id"], 4)
            self.assertEqual(posted[1][0], "http://ground/event")

    def test_replay_rejects_missing_detection_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = Namespace(
                session_dir=Path(temporary), overlay_url="http://ground/overlay",
                event_url=None, token="token", delay_ms=0, start_delay_ms=0,
                speed=1, fps=30, start_frame=0, end_frame=None,
                mission_id=None, capture_epoch=None, timeout=1, dry_run=True,
            )
            with self.assertRaisesRegex(ValueError, "missing detection sidecar"):
                replay(args)


if __name__ == "__main__":
    unittest.main()
