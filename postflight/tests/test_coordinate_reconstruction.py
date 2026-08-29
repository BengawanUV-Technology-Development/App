import json
import math
import tempfile
import unittest
from pathlib import Path

from jetson.frame_metadata import FrameMetadataWriter
from postflight.coordinate_reconstruction import (
    CALIBRATED_ESTIMATE,
    ESTIMATED_UNCALIBRATED,
    NOT_AVAILABLE,
    CameraCalibration,
    CoordinateReconstructionAdapter,
    CoordinateReconstructionError,
    CoordinateReconstructionConfig,
    get_rotation_matrix,
    local_xy_to_geodetic,
    ray_ground_intersection,
    run_coordinate_reconstruction_from_artifacts,
    unproject_pixel_to_ray,
)
from postflight.offline_yolo import build_detection_record
from postflight.replay import (
    ReplayError,
    build_replay_records,
    replay_mission,
)


MISSION_ID = "mission-44444444-4444-4444-8444-444444444444"


def calibration(*, validated=True, mounting=True):
    return CameraCalibration(
        camera_id="arducam-0",
        image_width=1000,
        image_height=500,
        fx=500.0,
        fy=500.0,
        cx=500.0,
        cy=250.0,
        mounting_rpy_deg=(0.0, 0.0, 0.0) if mounting else None,
        validated=validated,
    )


def synchronized_detection(**overrides):
    record = {
        "schema_version": 1,
        "record_type": "detection",
        "detection_id": f"{MISSION_ID}:0:0",
        "mission_id": MISSION_ID,
        "capture_epoch": 1,
        "frame_id": 0,
        "camera_id": "arducam-0",
        "capture_utc_ns": 1_500,
        "bbox_xyxy_normalized": [0.49, 0.48, 0.51, 0.52],
        "telemetry_sync_status": "synchronized",
        "latitude": 0.0,
        "longitude": 0.0,
        "altitude": 10.0,
        "altitude_agl_m": 10.0,
        "roll": 0.0,
        "pitch": 0.0,
        "yaw": 0.0,
        "altitude_reference": "AGL",
        "telemetry": {
            "source_timestamp_before": 1_000,
            "source_timestamp_after": 2_000,
            "interpolation": "linear",
        },
    }
    record.update(overrides)
    return record


class CoordinateReconstructionTests(unittest.TestCase):
    @staticmethod
    def _ground_intersection(
        u, v, *, roll=0.0, pitch=0.0, yaw=0.0, altitude=10.0
    ):
        rotation = get_rotation_matrix(roll, pitch, yaw)
        return ray_ground_intersection(
            (0.0, 0.0, altitude),
            unproject_pixel_to_ray(
                u,
                v,
                rotation,
                (
                    (1.0 / 500.0, 0.0, -1.0),
                    (0.0, 1.0 / 500.0, -0.5),
                    (0.0, 0.0, 1.0),
                ),
            ),
            0.0,
        )

    def test_reference_center_ray_intersects_ground_origin(self):
        rotation = get_rotation_matrix(0.0, 0.0, 0.0)
        ray = unproject_pixel_to_ray(
            500.0,
            250.0,
            rotation,
            (
                (1.0 / 500.0, 0.0, -1.0),
                (0.0, 1.0 / 500.0, -0.5),
                (0.0, 0.0, 1.0),
            ),
        )
        self.assertAlmostEqual(ray[0], 0.0)
        self.assertAlmostEqual(ray[1], 0.0)
        self.assertAlmostEqual(ray[2], -1.0)
        self.assertEqual(ray_ground_intersection((0.0, 0.0, 10.0), ray, 0.0), (0.0, 0.0))

    def test_reference_yaw_maps_camera_right_to_world_north(self):
        rotation = get_rotation_matrix(0.0, 0.0, 90.0)
        ray = unproject_pixel_to_ray(
            1000.0,
            250.0,
            rotation,
            (
                (1.0 / 500.0, 0.0, -1.0),
                (0.0, 1.0 / 500.0, -0.5),
                (0.0, 0.0, 1.0),
            ),
        )
        intersection = ray_ground_intersection((0.0, 0.0, 10.0), ray, 0.0)
        self.assertIsNotNone(intersection)
        self.assertAlmostEqual(intersection[0], 0.0, places=7)
        self.assertAlmostEqual(intersection[1], 10.0, places=7)

    def test_horizon_ray_is_rejected(self):
        rotation = get_rotation_matrix(0.0, 90.0, 0.0)
        ray = unproject_pixel_to_ray(
            500.0,
            250.0,
            rotation,
            (
                (1.0 / 500.0, 0.0, -1.0),
                (0.0, 1.0 / 500.0, -0.5),
                (0.0, 0.0, 1.0),
            ),
        )
        self.assertIsNone(ray_ground_intersection((0.0, 0.0, 10.0), ray, 0.0))

    def test_geodetic_conversion_uses_x_east_y_north(self):
        latitude, longitude = local_xy_to_geodetic(0.0, 0.0, 1.0, 1.0)
        expected_degree = 180.0 / 3.141592653589793 / 6_378_137.0
        self.assertAlmostEqual(latitude, expected_degree, places=10)
        self.assertAlmostEqual(longitude, expected_degree, places=10)

    def test_pixels_left_right_map_to_local_west_east(self):
        left = self._ground_intersection(400.0, 250.0)
        right = self._ground_intersection(600.0, 250.0)
        self.assertAlmostEqual(left[0], -2.0, places=7)
        self.assertAlmostEqual(right[0], 2.0, places=7)
        self.assertAlmostEqual(left[1], 0.0, places=7)
        self.assertAlmostEqual(right[1], 0.0, places=7)

    def test_pixels_forward_back_map_to_local_north_south(self):
        top = self._ground_intersection(500.0, 150.0)
        bottom = self._ground_intersection(500.0, 350.0)
        self.assertAlmostEqual(top[1], 2.0, places=7)
        self.assertAlmostEqual(bottom[1], -2.0, places=7)

    def test_roll_and_pitch_rotate_center_ray(self):
        rolled = self._ground_intersection(500.0, 250.0, roll=10.0)
        pitched = self._ground_intersection(500.0, 250.0, pitch=10.0)
        expected = 10.0 * math.tan(math.radians(10.0))
        self.assertAlmostEqual(rolled[1], expected, places=7)
        self.assertAlmostEqual(pitched[0], -expected, places=7)

    def test_off_center_projection_scales_with_altitude(self):
        low = self._ground_intersection(600.0, 250.0, altitude=10.0)
        high = self._ground_intersection(600.0, 250.0, altitude=20.0)
        self.assertAlmostEqual(low[0], 2.0, places=7)
        self.assertAlmostEqual(high[0], 4.0, places=7)

    def test_calibration_json_requires_typed_mounting_and_validation_flag(self):
        base = {
            "camera_id": "arducam-0",
            "image_width": 1000,
            "image_height": 500,
            "fx": 500.0,
            "fy": 500.0,
            "cx": 500.0,
            "cy": 250.0,
        }
        with self.assertRaises(CoordinateReconstructionError):
            CameraCalibration.from_dict({**base, "mounting_rpy_deg": {"roll": 0}})
        with self.assertRaises(CoordinateReconstructionError):
            CameraCalibration.from_dict({**base, "validated": "true"})

    def test_calibrated_center_estimate(self):
        adapter = CoordinateReconstructionAdapter(
            calibration(),
            config=CoordinateReconstructionConfig(camera_attitude_frame="body"),
        )
        result = adapter.reconstruct(synchronized_detection())
        self.assertEqual(result["status"], CALIBRATED_ESTIMATE)
        self.assertAlmostEqual(result["latitude"], 0.0, places=10)
        self.assertAlmostEqual(result["longitude"], 0.0, places=10)
        self.assertAlmostEqual(result["local_offset_east_m"], 0.0, places=10)
        self.assertAlmostEqual(result["local_offset_north_m"], 0.0, places=10)

    def test_relative_home_altitude_is_not_silently_used_as_agl(self):
        adapter = CoordinateReconstructionAdapter(calibration())
        result = adapter.reconstruct(
            synchronized_detection(altitude_reference="RELATIVE_HOME")
        )
        self.assertEqual(result["status"], NOT_AVAILABLE)
        self.assertEqual(result["error_code"], "INVALID_RECONSTRUCTION_INPUT")
        self.assertIn("AGL", result["reason"])

    def test_generic_relative_altitude_is_not_accepted_as_agl(self):
        adapter = CoordinateReconstructionAdapter(calibration())
        result = adapter.reconstruct(
            synchronized_detection(altitude_agl_m=None)
        )
        self.assertEqual(result["status"], NOT_AVAILABLE)
        self.assertEqual(result["error_code"], "INVALID_RECONSTRUCTION_INPUT")
        self.assertIn("altitude_agl_m", result["reason"])

    def test_synthetic_clock_alignment_is_rejected(self):
        adapter = CoordinateReconstructionAdapter(calibration())
        result = adapter.reconstruct(
            synchronized_detection(
                telemetry_sync_status="prototype_synthetic_clock_aligned"
            )
        )
        self.assertEqual(result["status"], NOT_AVAILABLE)
        self.assertEqual(result["error_code"], "TELEMETRY_NOT_SYNCHRONIZED")

    def test_missing_camera_mounting_is_rejected_for_body_attitude(self):
        adapter = CoordinateReconstructionAdapter(calibration(mounting=False))
        result = adapter.reconstruct(synchronized_detection())
        self.assertEqual(result["status"], NOT_AVAILABLE)
        self.assertEqual(result["error_code"], "INVALID_RECONSTRUCTION_INPUT")
        self.assertIn("mounting", result["reason"])

    def test_explicit_but_unvalidated_model_returns_uncalibrated_estimate(self):
        adapter = CoordinateReconstructionAdapter(calibration(validated=False))
        result = adapter.reconstruct(synchronized_detection())
        self.assertEqual(result["status"], ESTIMATED_UNCALIBRATED)
        self.assertIsNotNone(result["latitude"])
        self.assertIn("not validated", result["reason"])

    def test_artifact_path_uses_existing_source_time_synchronization(self):
        with tempfile.TemporaryDirectory(prefix="buv-coordinate-test-") as temp_dir:
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
                class_id=0,
                class_name="target",
                confidence=0.9,
                bbox_xyxy=[400, 200, 600, 300],
                image_width=1000,
                image_height=500,
            )
            detections_path.write_text(
                json.dumps(detection) + "\n", encoding="utf-8"
            )

            telemetry_path = root / "telemetry.jsonl"
            samples = []
            for timestamp, latitude, longitude in ((1_000, 0.0, 0.0), (2_000, 0.0, 0.0)):
                samples.append(
                    {
                        "record_type": "telemetry_sample",
                        "mission_id": MISSION_ID,
                        "source_timestamp": timestamp,
                        "source_time_valid": True,
                        "source_clock_domain": "utc",
                        "receive_timestamp": timestamp + 10_000,
                        "payload": {
                            "latitude": latitude,
                            "longitude": longitude,
                            "relative_altitude": 10.0,
                            "altitude_agl_m": 10.0,
                            "roll_deg": 0.0,
                            "pitch_deg": 0.0,
                            "yaw_deg": 0.0,
                        },
                    }
                )
            telemetry_path.write_text(
                "".join(json.dumps(sample) + "\n" for sample in samples),
                encoding="utf-8",
            )

            output_path = root / "coordinates.jsonl"
            report = run_coordinate_reconstruction_from_artifacts(
                detections_path,
                frames_path,
                telemetry_path,
                output_path,
                calibration(),
                altitude_reference="AGL",
            )

            self.assertEqual(report["synchronization"]["synchronized"], 1)
            self.assertEqual(
                report["reconstruction"]["status_counts"],
                {CALIBRATED_ESTIMATE: 1},
            )
            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(output["frame_id"], 0)
            self.assertEqual(output["coordinate"]["status"], CALIBRATED_ESTIMATE)

    def test_replay_preserves_frame_identity_and_complete_state(self):
        with tempfile.TemporaryDirectory(prefix="buv-replay-test-") as temp_dir:
            root = Path(temp_dir)
            frames_path = root / "frames.jsonl"
            writer = FrameMetadataWriter(frames_path, MISSION_ID, "arducam-0")
            writer.start()
            first = writer.record_frame(
                capture_utc_ns=1_000,
                capture_monotonic_ns=100,
                source_pts_ns=10,
            )
            second = writer.record_frame(
                capture_utc_ns=2_000,
                capture_monotonic_ns=1_100,
                source_pts_ns=20,
            )
            writer.stop()

            telemetry_path = root / "telemetry.jsonl"
            samples = []
            for timestamp, latitude in ((1_000, -7.5), (2_000, -7.4)):
                samples.append(
                    {
                        "record_type": "telemetry_sample",
                        "mission_id": MISSION_ID,
                        "source_timestamp": timestamp,
                        "source_time_valid": True,
                        "source_clock_domain": "utc",
                        "payload": {
                            "latitude": latitude,
                            "longitude": 110.8,
                            "relative_altitude": 10.0,
                            "roll_deg": 0.0,
                            "pitch_deg": 0.0,
                            "yaw_deg": 90.0,
                        },
                    }
                )
            telemetry_path.write_text(
                "".join(json.dumps(sample) + "\n" for sample in samples),
                encoding="utf-8",
            )

            records = build_replay_records(frames_path, telemetry_path)

            self.assertEqual([record["frame_id"] for record in records], [0, 1])
            self.assertEqual([record["video_frame_index"] for record in records], [0, 1])
            self.assertEqual(records[0]["capture_utc_ns"], first["capture_utc_ns"])
            self.assertEqual(records[1]["capture_utc_ns"], second["capture_utc_ns"])
            self.assertEqual(records[0]["telemetry_sync_status"], "synchronized")
            self.assertAlmostEqual(records[1]["telemetry"]["latitude"], -7.4)

    def test_replay_writes_metadata_only_without_video_sleep(self):
        with tempfile.TemporaryDirectory(prefix="buv-replay-output-") as temp_dir:
            root = Path(temp_dir)
            frames_path = root / "frames.jsonl"
            writer = FrameMetadataWriter(frames_path, MISSION_ID, "arducam-0")
            writer.start()
            writer.record_frame(
                capture_utc_ns=1_000,
                capture_monotonic_ns=100,
                source_pts_ns=10,
            )
            writer.stop()
            telemetry_path = root / "telemetry.jsonl"
            telemetry_path.write_text(
                json.dumps(
                    {
                        "record_type": "telemetry_sample",
                        "mission_id": MISSION_ID,
                        "source_timestamp": 1_000,
                        "source_time_valid": True,
                        "source_clock_domain": "utc",
                        "payload": {
                            "latitude": -7.5,
                            "longitude": 110.8,
                            "relative_altitude": 10.0,
                            "roll_deg": 0.0,
                            "pitch_deg": 0.0,
                            "yaw_deg": 90.0,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output_path = root / "replay.jsonl"

            report = replay_mission(
                frames_path,
                telemetry_path,
                output_path,
                realtime=False,
            )

            self.assertEqual(report["frames_processed"], 1)
            self.assertFalse(report["video_checked"])
            self.assertEqual(len(output_path.read_text(encoding="utf-8").splitlines()), 1)

            with self.assertRaises(ReplayError):
                replay_mission(frames_path, telemetry_path, output_path, realtime=False)


if __name__ == "__main__":
    unittest.main()
