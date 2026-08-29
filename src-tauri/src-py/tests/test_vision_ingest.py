import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models import TelemetrySample  # noqa: E402
from app.routes.vision import init_vision_routes, vision_bp  # noqa: E402
from app.services.vision_ingest import (  # noqa: E402
    VisionDetectionService,
    VisionIngestError,
)
from postflight.synchronization import LiveTelemetryTimeline  # noqa: E402


MISSION_ID = "mission-11111111-1111-4111-8111-111111111111"


def valid_event(**overrides):
    event = {
        "type": "vision.detection_event",
        "schema_version": "2.0",
        "mission_id": MISSION_ID,
        "capture_epoch": 1,
        "frame_id": 7,
        "camera_id": "arducam",
        "capture_utc_ns": 1_500,
        "source_pts_ns": 1_500,
        "detection_id": "det-7",
        "class_id": 0,
        "class": "pedestrian",
        "confidence": 0.72,
        "bbox_normalized_xyxy": [0.25, 0.25, 0.5, 0.75],
        # The Ground must not trust this Jetson-provided placeholder.
        "coordinate": {"status": "CALIBRATED_ESTIMATE", "latitude": 0, "longitude": 0},
    }
    event.update(overrides)
    return event


def telemetry_sample(timestamp, *, valid=True, mission_id=MISSION_ID, **payload):
    return TelemetrySample(
        mission_id=mission_id,
        source_timestamp=timestamp,
        source_time_valid=valid,
        message_type="TEST",
        payload=payload,
    )


class LiveTelemetryTimelineTests(unittest.TestCase):
    def test_interpolation_uses_only_valid_source_time_samples(self):
        timeline = LiveTelemetryTimeline()
        timeline.append(
            telemetry_sample(
                1_000,
                latitude=-6.0,
                longitude=106.0,
                relative_altitude=10.0,
                roll_deg=1.0,
                pitch_deg=2.0,
                yaw_deg=3.0,
            )
        )
        timeline.append(
            telemetry_sample(
                2_000,
                latitude=-6.001,
                longitude=106.001,
                relative_altitude=12.0,
                roll_deg=3.0,
                pitch_deg=4.0,
                yaw_deg=5.0,
            )
        )
        timeline.append(
            telemetry_sample(
                1_500,
                valid=False,
                latitude=99.0,
                longitude=99.0,
            )
        )

        state = timeline.interpolate(1_500)

        self.assertAlmostEqual(state["latitude"], -6.0005)
        self.assertAlmostEqual(state["longitude"], 106.0005)
        self.assertAlmostEqual(state["altitude"], 11.0)
        self.assertEqual(state["interpolation"], "linear")


class VisionDetectionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="vision-ingest-")
        self.service = VisionDetectionService()
        self.mission_dir = Path(self.temp_dir.name) / MISSION_ID
        self.service.start(MISSION_ID, artifact_dir=self.mission_dir)
        self.service.record_telemetry(
            telemetry_sample(
                1_000,
                latitude=-6.0,
                longitude=106.0,
                relative_altitude=10.0,
                roll_deg=1.0,
                pitch_deg=2.0,
                yaw_deg=3.0,
            )
        )
        self.service.record_telemetry(
            telemetry_sample(
                2_000,
                latitude=-6.001,
                longitude=106.001,
                relative_altitude=12.0,
                roll_deg=3.0,
                pitch_deg=4.0,
                yaw_deg=5.0,
            )
        )

    def tearDown(self):
        self.service.stop()
        self.temp_dir.cleanup()

    def test_ingest_resolves_exact_identity_and_interpolated_telemetry(self):
        result = self.service.ingest_event(valid_event())

        self.assertEqual(result["mission_id"], MISSION_ID)
        self.assertEqual(result["frame_id"], 7)
        self.assertEqual(result["capture_utc_ns"], 1_500)
        self.assertEqual(result["telemetry_sync_status"], "synchronized")
        self.assertAlmostEqual(result["latitude"], -6.0005)
        self.assertAlmostEqual(result["longitude"], 106.0005)
        self.assertAlmostEqual(result["altitude"], 11.0)
        self.assertEqual(result["coordinate"]["status"], "NOT_AVAILABLE")
        self.assertEqual(result["bbox"], [0.25, 0.25, 0.5, 0.75])

        artifact = self.mission_dir / "detections_with_telemetry.jsonl"
        with artifact.open(encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["detection_id"], "det-7")
        self.assertEqual(records[0]["source_record_type"], "vision.detection_event")

    def test_inbound_coordinate_is_never_trusted(self):
        result = self.service.ingest_event(valid_event())

        self.assertEqual(result["coordinate"]["status"], "NOT_AVAILABLE")
        self.assertIsNone(result["coordinate"]["latitude"])
        self.assertIsNone(result["coordinate"]["longitude"])

    def test_telemetry_without_mission_id_is_rejected_from_active_timeline(self):
        accepted = self.service.record_telemetry(
            telemetry_sample(
                2_500,
                mission_id=None,
                latitude=-6.0,
                longitude=106.0,
                relative_altitude=10.0,
                roll_deg=0.0,
                pitch_deg=0.0,
                yaw_deg=0.0,
            )
        )

        self.assertFalse(accepted)
        self.assertEqual(self.service.status()["telemetry_timeline_samples"], 2)

    def test_pending_detection_is_resolved_after_late_telemetry(self):
        pending = self.service.ingest_event(valid_event(capture_utc_ns=2_500))

        self.assertEqual(pending["processing_status"], "pending_telemetry")
        self.assertEqual(self.service.status()["pending_detections"], 1)

        self.service.record_telemetry(
            telemetry_sample(
                3_000,
                latitude=-6.002,
                longitude=106.002,
                relative_altitude=14.0,
                roll_deg=5.0,
                pitch_deg=6.0,
                yaw_deg=7.0,
            )
        )
        self.service.flush_pending()

        latest = self.service.latest()["detection"]
        self.assertEqual(latest["detection_id"], "det-7")
        self.assertEqual(latest["processing_status"], "resolved")
        self.assertEqual(latest["telemetry_sync_status"], "synchronized")
        self.assertEqual(self.service.status()["pending_detections"], 0)

    def test_conflicting_duplicate_detection_id_is_rejected(self):
        self.service.ingest_event(valid_event())

        with self.assertRaisesRegex(VisionIngestError, "detection_id conflicts"):
            self.service.ingest_event(
                valid_event(bbox_normalized_xyxy=[0.1, 0.1, 0.2, 0.2])
            )

    def test_zero_area_bbox_is_rejected(self):
        with self.assertRaisesRegex(VisionIngestError, "positive area"):
            self.service.ingest_event(
                valid_event(bbox_normalized_xyxy=[0.25, 0.25, 0.25, 0.75])
            )

    def test_duplicate_detection_is_idempotent(self):
        first = self.service.ingest_event(valid_event())
        duplicate = self.service.ingest_event(valid_event())

        self.assertEqual(duplicate, first)
        artifact = self.mission_dir / "detections_with_telemetry.jsonl"
        self.assertEqual(len(artifact.read_text(encoding="utf-8").splitlines()), 1)

    def test_wrong_mission_is_rejected(self):
        with self.assertRaises(VisionIngestError):
            self.service.ingest_event(
                valid_event(
                    mission_id="mission-22222222-2222-4222-8222-222222222222"
                )
            )

    def test_class_id_is_required_by_detection_contract(self):
        with self.assertRaisesRegex(VisionIngestError, "class_id is required"):
            self.service.ingest_event(valid_event(class_id=None))

    def test_missing_telemetry_bracket_is_safe_and_auditable(self):
        result = self.service.ingest_event(valid_event(capture_utc_ns=9_000))

        self.assertEqual(result["telemetry_sync_status"], "unsynchronized")
        self.assertEqual(result["coordinate"]["status"], "NOT_AVAILABLE")
        self.assertEqual(result["coordinate"]["error_code"], "TELEMETRY_NOT_SYNCHRONIZED")
        self.assertIsNone(result["latitude"])

    def test_stop_finalizes_pending_detection_without_dropping_it(self):
        self.service.ingest_event(valid_event(capture_utc_ns=9_000))

        stopped = self.service.stop()

        self.assertEqual(stopped["accepted_detections"], 1)
        artifact = self.mission_dir / "detections_with_telemetry.jsonl"
        records = [
            json.loads(line)
            for line in artifact.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["processing_status"], "finalized_unsynchronized")
        self.assertEqual(records[0]["telemetry_sync_status"], "unsynchronized")


class VisionRouteTests(unittest.TestCase):
    def test_ingest_route_requires_token_and_returns_ack(self):
        with tempfile.TemporaryDirectory(prefix="vision-route-") as temp_dir:
            service = VisionDetectionService()
            service.start(MISSION_ID, artifact_dir=Path(temp_dir) / MISSION_ID)
            service.record_telemetry(
                telemetry_sample(
                    1_000,
                    latitude=-6.0,
                    longitude=106.0,
                    relative_altitude=10.0,
                    roll_deg=0.0,
                    pitch_deg=0.0,
                    yaw_deg=0.0,
                )
            )
            service.record_telemetry(
                telemetry_sample(
                    2_000,
                    latitude=-6.0,
                    longitude=106.0,
                    relative_altitude=10.0,
                    roll_deg=0.0,
                    pitch_deg=0.0,
                    yaw_deg=0.0,
                )
            )
            init_vision_routes(service, ingest_token="secret")

            from flask import Flask

            app = Flask(__name__)
            app.register_blueprint(vision_bp)
            with app.test_client() as client:
                unauthorized = client.post("/api/v1/detection/ingest", json=valid_event())
                accepted = client.post(
                    "/api/v1/detection/ingest",
                    json=valid_event(),
                    headers={"Authorization": "Bearer secret"},
                )

            service.stop()

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(accepted.status_code, 202)
        self.assertTrue(accepted.get_json()["accepted"])
        self.assertEqual(accepted.get_json()["detection"]["frame_id"], 7)

    def test_remote_read_route_requires_bearer_token(self):
        service = VisionDetectionService()
        service.start(MISSION_ID)
        init_vision_routes(service, ingest_token="secret", read_token="read-secret")

        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(vision_bp)
        with app.test_client() as client:
            remote = client.get(
                "/api/v1/detection/status",
                environ_base={"REMOTE_ADDR": "100.64.0.8"},
            )
            authorized = client.get(
                "/api/v1/detection/status",
                environ_base={"REMOTE_ADDR": "100.64.0.8"},
                headers={"Authorization": "Bearer read-secret"},
            )
        service.stop()

        self.assertEqual(remote.status_code, 401)
        self.assertEqual(authorized.status_code, 200)


if __name__ == "__main__":
    unittest.main()
