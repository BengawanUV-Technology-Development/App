import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from jetson.frame_metadata import FrameMetadataWriter
from postflight.offline_yolo import build_detection_record, run_offline_yolo
from postflight.synchronization import synchronize_detections


MISSION_ID = "mission-33333333-3333-4333-8333-333333333333"


class PostFlightSynchronizationTests(unittest.TestCase):
    def test_detection_frame_and_telemetry_are_interpolated_by_source_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frames_path = root / "frames.jsonl"
            writer = FrameMetadataWriter(frames_path, MISSION_ID, "arducam-0")
            writer.start()
            frame = writer.record_frame(
                capture_utc_ns=1_500,
                capture_monotonic_ns=500,
                source_pts_ns=50,
            )
            writer.stop()

            detections_path = root / "detections.jsonl"
            detection = build_detection_record(
                mission_id=MISSION_ID,
                frame=frame,
                detection_index=0,
                class_id=7,
                class_name="target",
                confidence=0.9,
                bbox_xyxy=[100, 50, 300, 250],
                image_width=1000,
                image_height=500,
            )
            detections_path.write_text(json.dumps(detection) + "\n", encoding="utf-8")

            telemetry_path = root / "telemetry.jsonl"
            samples = [
                {
                    "record_type": "telemetry_sample",
                    "mission_id": MISSION_ID,
                    "source_timestamp": 1_000,
                    "source_time_valid": True,
                    "source_clock_domain": "utc",
                    "receive_timestamp": 10_000,
                    "payload": {
                        "latitude": 1.0,
                        "longitude": 2.0,
                        "relative_altitude": 10.0,
                        "roll_deg": 0.0,
                        "pitch_deg": 2.0,
                        "yaw_deg": 10.0,
                    },
                },
                {
                    "record_type": "telemetry_sample",
                    "mission_id": MISSION_ID,
                    "source_timestamp": 2_000,
                    "source_time_valid": True,
                    "source_clock_domain": "utc",
                    "receive_timestamp": 11_000,
                    "payload": {
                        "latitude": 3.0,
                        "longitude": 4.0,
                        "relative_altitude": 20.0,
                        "roll_deg": 4.0,
                        "pitch_deg": 6.0,
                        "yaw_deg": 30.0,
                    },
                },
            ]
            telemetry_path.write_text(
                "".join(json.dumps(sample) + "\n" for sample in samples),
                encoding="utf-8",
            )

            output_path = root / "synced-detections.jsonl"
            report = synchronize_detections(
                detections_path,
                frames_path,
                telemetry_path,
                output_path,
            )
            self.assertEqual(report["synchronized"], 1)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["frame_id"], 0)
            self.assertEqual(result["capture_utc_ns"], 1_500)
            self.assertAlmostEqual(result["latitude"], 2.0)
            self.assertAlmostEqual(result["longitude"], 3.0)
            self.assertAlmostEqual(result["altitude"], 15.0)
            self.assertAlmostEqual(result["roll"], 2.0)
            self.assertAlmostEqual(result["pitch"], 4.0)
            self.assertAlmostEqual(result["yaw"], 20.0)

    def test_detection_bbox_is_normalized_to_master_image(self):
        frame = {
            "mission_id": MISSION_ID,
            "capture_epoch": 1,
            "frame_id": 4,
            "camera_id": "arducam-0",
            "capture_utc_ns": 1_500,
            "source_pts_ns": 50,
        }
        record = build_detection_record(
            mission_id=MISSION_ID,
            frame=frame,
            detection_index=0,
            class_id=1,
            class_name="object",
            confidence=0.8,
            bbox_xyxy=[100, 50, 300, 250],
            image_width=1000,
            image_height=500,
        )
        self.assertEqual(record["bbox_xyxy_normalized"], [0.1, 0.1, 0.3, 0.5])

    def test_offline_runner_keeps_detection_on_metadata_frame(self):
        class FakeImage:
            shape = (500, 1000, 3)

        class FakeCapture:
            def __init__(self, _path):
                self.reads = 0

            def isOpened(self):
                return True

            def read(self):
                self.reads += 1
                return (self.reads == 1, FakeImage() if self.reads == 1 else None)

            def release(self):
                return None

        class FakeBoxes:
            xyxy = [[100, 50, 300, 250]]
            cls = [7]
            conf = [0.9]

        class FakeResult:
            boxes = FakeBoxes()
            names = {7: "target"}

        class FakeYolo:
            names = {7: "target"}

            def __init__(self, _model):
                pass

            def predict(self, _image, **_kwargs):
                return [FakeResult()]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frames_path = root / "frames.jsonl"
            writer = FrameMetadataWriter(frames_path, MISSION_ID, "arducam-0")
            writer.start()
            writer.record_frame(
                capture_utc_ns=1_500,
                capture_monotonic_ns=500,
                source_pts_ns=50,
            )
            writer.stop()
            video_path = root / "video.mp4"
            model_path = root / "model.pt"
            output_path = root / "detections.jsonl"
            video_path.write_bytes(b"video")
            model_path.write_bytes(b"weights")
            fake_cv2 = types.SimpleNamespace(VideoCapture=FakeCapture)
            fake_ultralytics = types.SimpleNamespace(YOLO=FakeYolo)
            with patch.dict(
                sys.modules,
                {"cv2": fake_cv2, "ultralytics": fake_ultralytics},
            ):
                report = run_offline_yolo(
                    video_path,
                    frames_path,
                    output_path,
                    model_path,
                )

            self.assertEqual(report["frames_processed"], 1)
            detection = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(detection["frame_id"], 0)
            self.assertEqual(detection["class_name"], "target")
            self.assertEqual(detection["bbox_xyxy_normalized"], [0.1, 0.1, 0.3, 0.5])
