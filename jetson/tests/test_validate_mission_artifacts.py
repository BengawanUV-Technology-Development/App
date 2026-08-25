import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jetson.frame_metadata import FrameMetadataWriter
from jetson.validate_mission_artifacts import (
    MissionArtifactValidationError,
    validate_mission_artifacts,
)


MISSION_ID = "mission-22222222-2222-4222-8222-222222222222"


class MissionArtifactValidationTests(unittest.TestCase):
    def test_valid_artifacts_are_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mission_dir = root / MISSION_ID
            frames = FrameMetadataWriter(
                mission_dir / "frames.jsonl", MISSION_ID, "arducam-0"
            )
            frames.start()
            frames.record_frame(
                capture_utc_ns=1_700_000_000_000_000_000,
                capture_monotonic_ns=100,
                source_pts_ns=10,
            )
            frames.stop()
            (mission_dir / "video.mp4").write_bytes(b"test-video")

            telemetry_path = root / "telemetry.jsonl"
            telemetry_path.write_text(
                "".join(
                    json.dumps(record) + "\n"
                    for record in [
                        {
                            "record_type": "mission_event",
                            "mission_id": MISSION_ID,
                            "receive_timestamp": 1,
                            "message_type": "MISSION_START",
                        },
                        {
                            "record_type": "telemetry_sample",
                            "mission_id": MISSION_ID,
                            "receive_timestamp": 2,
                            "source_time_valid": True,
                            "message_type": "GLOBAL_POSITION_INT",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            with patch(
                "jetson.validate_mission_artifacts.shutil.which", return_value=None
            ):
                report = validate_mission_artifacts(mission_dir, telemetry_path)
            self.assertTrue(report["ok"])
            self.assertEqual(report["frames"]["frame_count"], 1)
            self.assertEqual(report["telemetry"]["source_time_valid_count"], 1)

    def test_missing_frames_file_fails_acceptance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mission_dir = root / MISSION_ID
            mission_dir.mkdir()
            telemetry = root / "telemetry.jsonl"
            telemetry.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(MissionArtifactValidationError):
                validate_mission_artifacts(mission_dir, telemetry)

    def test_mission_root_resolves_latest_epoch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / MISSION_ID
            epoch_dir = root / "epochs" / "0001"
            frames = FrameMetadataWriter(
                epoch_dir / "frames.jsonl", MISSION_ID, "arducam"
            )
            frames.start()
            frames.record_frame(
                capture_utc_ns=1_700_000_000_000_000_000,
                capture_monotonic_ns=100,
                source_pts_ns=10,
            )
            frames.stop()
            (epoch_dir / "video.mp4").write_bytes(b"test-video")
            telemetry = root.parent / "telemetry.jsonl"
            telemetry.write_text(
                json.dumps(
                    {
                        "record_type": "telemetry_sample",
                        "mission_id": MISSION_ID,
                        "receive_timestamp": 2,
                        "source_time_valid": True,
                        "message_type": "GLOBAL_POSITION_INT",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch(
                "jetson.validate_mission_artifacts.shutil.which", return_value=None
            ):
                report = validate_mission_artifacts(root, telemetry)
            self.assertEqual(report["artifact_directory"], str(epoch_dir))
            self.assertEqual(report["capture_epoch"], 1)
