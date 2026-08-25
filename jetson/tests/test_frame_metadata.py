import json
import tempfile
import unittest
from pathlib import Path

from jetson.frame_metadata import (
    CaptureClock,
    FrameMetadataError,
    FrameMetadataWriter,
    FrameMetadataValidationError,
    gst_buffer_pts_ns,
    validate_frame_metadata,
)


MISSION_ID = "mission-11111111-1111-4111-8111-111111111111"


class _Buffer:
    def __init__(self, pts):
        self.pts = pts


class FrameMetadataTests(unittest.TestCase):
    def test_capture_writer_preserves_canonical_identity_and_source_pts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "frames.jsonl"
            writer = FrameMetadataWriter(path, MISSION_ID, "arducam-0")
            writer.start()

            first_clock = CaptureClock(1_700_000_000_000_000_000, 100)
            first = writer.record_gst_buffer(
                _Buffer(33_333_333), capture_clock=first_clock
            )
            second = writer.record_frame(
                capture_utc_ns=1_700_000_000_033_333_333,
                capture_monotonic_ns=100_033_333,
                source_pts_ns=66_666_666,
            )
            writer.stop()

            self.assertEqual(first["frame_id"], 0)
            self.assertEqual(first["source_pts_ns"], 33_333_333)
            self.assertEqual(second["frame_id"], 1)
            self.assertEqual(second["capture_epoch"], 1)
            report = validate_frame_metadata(path, expected_mission_id=MISSION_ID)
            self.assertEqual(report["frame_count"], 2)
            self.assertEqual(report["last_frame_id"], 1)
            self.assertEqual(report["missing_source_pts"], 0)

    def test_missing_pts_is_rejected_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = FrameMetadataWriter(
                Path(temp_dir) / "frames.jsonl", MISSION_ID, "arducam-0"
            )
            writer.start()
            with self.assertRaises(FrameMetadataError):
                writer.record_gst_buffer(
                    _Buffer((1 << 64) - 1),
                    capture_clock=CaptureClock(1_700_000_000_000_000_000, 100),
                )
            writer.stop()

    def test_append_capture_epoch_keeps_frame_identity_and_allows_pts_reset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "frames.jsonl"
            first = FrameMetadataWriter(path, MISSION_ID, "arducam-0")
            first.start()
            first.record_frame(
                capture_utc_ns=1_700_000_000_000_000_000,
                capture_monotonic_ns=100,
                source_pts_ns=100,
            )
            first.stop()

            second = FrameMetadataWriter(
                path,
                MISSION_ID,
                "arducam-0",
                capture_epoch=2,
                append=True,
            )
            second.start()
            second.record_frame(
                capture_utc_ns=1_700_000_000_100_000_000,
                capture_monotonic_ns=200,
                source_pts_ns=0,
            )
            second.stop()

            report = validate_frame_metadata(path, expected_mission_id=MISSION_ID)
            self.assertEqual(report["frame_count"], 2)
            self.assertEqual(report["capture_epochs"], [1, 2])

    def test_validator_rejects_timestamp_regression(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "frames.jsonl"
            records = [
                {
                    "mission_id": MISSION_ID,
                    "capture_epoch": 1,
                    "frame_id": 0,
                    "camera_id": "arducam-0",
                    "capture_utc_ns": 200,
                    "capture_monotonic_ns": 200,
                    "source_pts_ns": 200,
                },
                {
                    "mission_id": MISSION_ID,
                    "capture_epoch": 1,
                    "frame_id": 1,
                    "camera_id": "arducam-0",
                    "capture_utc_ns": 100,
                    "capture_monotonic_ns": 300,
                    "source_pts_ns": 300,
                },
            ]
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            with self.assertRaises(FrameMetadataValidationError):
                validate_frame_metadata(path, expected_mission_id=MISSION_ID)

    def test_gst_none_pts_is_not_synthesized(self):
        self.assertIsNone(gst_buffer_pts_ns(_Buffer(None)))
        self.assertIsNone(gst_buffer_pts_ns(_Buffer((1 << 64) - 1)))
        self.assertEqual(gst_buffer_pts_ns(_Buffer(0)), 0)
