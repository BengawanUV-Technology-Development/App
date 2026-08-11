import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from collections import OrderedDict, deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


APP_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jetson.arducam_split_pipeline import (  # noqa: E402
    DetectionWorker,
    FramePacket,
    RtpNetworkSender,
    SplitPipeline,
    build_pipeline_description,
    parse_args,
    read_system_health,
    scale_bbox,
)
from jetson.model_provenance import (  # noqa: E402
    ModelProvenanceError,
    ProductionModelManifest,
)


class ArducamSplitPipelineTests(unittest.TestCase):
    @staticmethod
    def _write_test_manifest(directory: str) -> tuple[Path, Path]:
        checkpoint = Path(directory) / "best.pt"
        checkpoint.write_bytes(b"deterministic-test-checkpoint")
        manifest = Path(directory) / "model.json"
        manifest.write_text(json.dumps({
            "schema_version": "1",
            "model_id": "test-model",
            "architecture": "s-yolov11",
            "variant": "baseline",
            "checkpoint": {
                "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "size_bytes": checkpoint.stat().st_size,
            },
            "runtime": {
                "device": "cuda:0", "imgsz": 640, "confidence": 0.45, "sahi": False,
            },
        }), encoding="utf-8")
        return checkpoint, manifest

    def test_v2_mission_epoch_layout_is_created_without_legacy_metadata(self):
        import tempfile

        mission_id = "mission-00000000-0000-0000-0000-000000000002"
        with tempfile.TemporaryDirectory() as temporary:
            args = parse_args([
                "--host", "100.64.0.10", "--record-dir", temporary,
                "--allow-root-record-dir", "--min-free-bytes", "0",
                "--mission-id", mission_id, "--capture-epoch", "2",
            ])
            pipeline = SplitPipeline(args)
            try:
                epoch_dir = Path(temporary).resolve() / mission_id / "epochs" / "0002"
                self.assertEqual(pipeline.session_dir, epoch_dir)
                self.assertTrue((Path(temporary) / mission_id / "mission.json").is_file())
                self.assertTrue((epoch_dir / "epoch.json").is_file())
                self.assertFalse((epoch_dir / "metadata.json").exists())
            finally:
                pipeline.sidecars.close()
                pipeline.worker.close()

    def test_default_pipeline_has_independent_highres_and_network_branches(self):
        args = parse_args(["--host", "100.64.0.10"])

        description = build_pipeline_description(args, Path("/tmp/video.mp4"))

        self.assertEqual(description.count("x264enc"), 2)
        self.assertIn("width=1920,height=1080", description)
        self.assertIn("width=960,height=540", description)
        self.assertIn("framerate=30/1", description)
        self.assertIn("framerate=15/1", description)
        self.assertIn("appsink name=highres_sink", description)
        self.assertIn("max-size-buffers=16", description)
        self.assertIn("drop=false", description)
        self.assertIn("rtph264pay name=preview_payloader pt=96", description)
        self.assertIn("identity name=preview_identity", description)
        self.assertIn("fragment-duration=1000", description)
        self.assertIn("fragment-mode=first-moov-then-finalise", description)
        self.assertIn("moov-recovery-file=\"/tmp/video.mp4.moov.recovery\"", description)
        self.assertIn("appsink name=network_sink", description)
        self.assertNotIn("udpsink", description)
        self.assertIn("filesink location=\"/tmp/video.mp4\"", description)

    def test_broken_thermal_sensor_does_not_stop_health_collection(self):
        broken_sensor = MagicMock()
        broken_sensor.read_text.side_effect = TypeError("sysfs returned no bytes")

        with patch(
            "jetson.arducam_split_pipeline.Path.glob",
            return_value=[broken_sensor],
        ):
            health = read_system_health()

        self.assertIsNone(health["temperature_c"])
        self.assertIn("ram_total_bytes", health)

    def test_source_probe_assigns_identity_before_pipeline_branches(self):
        pipeline = SplitPipeline.__new__(SplitPipeline)
        pipeline.args = SimpleNamespace(
            mission_id="mission-00000000-0000-0000-0000-000000000020",
            capture_epoch=3,
        )
        pipeline.gst = SimpleNamespace(
            CLOCK_TIME_NONE=-1,
            PadProbeReturn=SimpleNamespace(OK="ok"),
        )
        pipeline.frame_counter = 0
        pipeline._identity_condition = threading.Condition()
        pipeline._identity_by_pts = OrderedDict()
        pipeline._first_capture_monotonic_ns = None
        pipeline._last_capture_monotonic_ns = None
        pipeline.failure_error = None
        pipeline.loop = None
        pipeline.sidecars = MagicMock()
        pipeline.sidecars.submit.return_value = True
        probe_info = MagicMock()
        probe_info.get_buffer.return_value = SimpleNamespace(pts=123_000_000)

        with patch(
            "jetson.arducam_split_pipeline.time.time_ns",
            return_value=456_000_000,
        ), patch(
            "jetson.arducam_split_pipeline.time.monotonic_ns",
            return_value=789_000_000,
        ):
            result = pipeline._on_source_buffer(None, probe_info)

        packet = pipeline._identity_by_pts[123_000_000]
        self.assertEqual(result, "ok")
        self.assertEqual(packet.frame_id, 0)
        self.assertEqual(packet.capture_epoch, 3)
        self.assertEqual(packet.capture_utc_ns, 456_000_000)
        pipeline.sidecars.submit.assert_called_once_with(packet)

    def test_videorate_preview_pts_maps_to_nearest_canonical_frame(self):
        pipeline = SplitPipeline.__new__(SplitPipeline)
        pipeline.args = SimpleNamespace(high_fps=30.0)
        pipeline.gst = SimpleNamespace(
            CLOCK_TIME_NONE=-1,
            PadProbeReturn=SimpleNamespace(OK="ok"),
        )
        pipeline._identity_condition = threading.Condition()
        pipeline._identity_by_pts = OrderedDict()
        pipeline._preview_identity_by_pts = OrderedDict()
        pipeline._preview_identity_queue = deque(maxlen=512)
        pipeline._active_preview_packet = None
        pipeline._identity_miss_count = 0
        first = FramePacket(
            "mission-00000000-0000-0000-0000-000000000020",
            1, 10, "arducam", 1, 1, 333_333_333, None,
        )
        second = FramePacket(
            first.mission_id,
            1, 11, "arducam", 2, 2, 366_666_666, None,
        )
        pipeline._identity_by_pts[first.pts_ns] = first
        pipeline._identity_by_pts[second.pts_ns] = second
        probe_info = MagicMock()
        # A rounded 15 FPS PTS is deliberately not equal to either master PTS.
        probe_info.get_buffer.return_value = SimpleNamespace(pts=334_000_000)

        result = pipeline._on_preview_buffer(None, probe_info)

        self.assertEqual(result, "ok")
        self.assertIs(pipeline._preview_identity_by_pts[334_000_000], first)
        self.assertIs(pipeline._wait_for_preview_identity(334_000_000), first)
        self.assertIs(pipeline._preview_identity_queue[0], first)
        self.assertEqual(pipeline._on_rtp_access_unit(None, None), "ok")
        self.assertIs(pipeline._active_preview_packet, first)
        self.assertEqual(pipeline._identity_miss_count, 0)

    def test_bbox_is_mapped_from_highres_to_network_coordinates(self):
        self.assertEqual(
            scale_bbox([100, 200, 500, 800], 1920, 1080, 960, 540),
            [50, 100, 250, 400],
        )

    def test_invalid_network_host_is_rejected(self):
        args = parse_args(["--host", "gcs;rm"])

        with self.assertRaises(ValueError):
            build_pipeline_description(args, Path("/tmp/video.mp4"))

    def test_network_sender_does_not_block_pipeline_on_udp_queue(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []

            def sendto(self, packet, destination):
                self.sent.append((packet, destination))

            def close(self):
                return None

        fake_socket = FakeSocket()
        sender = RtpNetworkSender("127.0.0.1", 5000)
        try:
            with patch(
                "jetson.arducam_split_pipeline.socket.socket",
                return_value=fake_socket,
            ), patch(
                "jetson.arducam_split_pipeline.socket.getaddrinfo",
                return_value=[(2, 2, 17, "", ("127.0.0.1", 5000))],
            ):
                sender.start()
                sender.submit(b"rtp-test")
                deadline = time.time() + 1
                while sender.packets_sent < 1 and time.time() < deadline:
                    time.sleep(0.01)
            self.assertEqual(fake_socket.sent[0][0], b"rtp-test")
            self.assertEqual(sender.packets_sent, 1)
        finally:
            sender.stop()

    def test_model_manifest_locks_checkpoint_and_runtime_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint, manifest_path = self._write_test_manifest(temporary)
            manifest = ProductionModelManifest(manifest_path)
            manifest.validate_runtime(device="cuda:0", imgsz=640, confidence=0.45, sahi=False)
            verified = manifest.verify(checkpoint)
            self.assertEqual(verified.model_id, "test-model")

            checkpoint.write_bytes(b"tampered-checkpoint")
            with self.assertRaisesRegex(ModelProvenanceError, "mismatch"):
                manifest.verify(checkpoint)
            with self.assertRaisesRegex(ModelProvenanceError, "SAHI"):
                manifest.validate_runtime(device="cuda:0", imgsz=640, confidence=0.45, sahi=True)

    def test_inference_queue_drops_oldest_and_keeps_newest(self):
        class FakeRunner:
            mode = "ultralytics"

            def __init__(self, *_args):
                pass

            def predict(self, _image):
                return []

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint, manifest = self._write_test_manifest(temporary)
            args = parse_args([
                "--host", "127.0.0.1", "--weights", str(checkpoint),
                "--model-manifest", str(manifest),
            ])
            with patch("jetson.arducam_split_pipeline.DetectionRunner", FakeRunner):
                worker = DetectionWorker(args, Path(temporary), time.time())
            first = FramePacket("mission-00000000-0000-0000-0000-000000000010", 1, 1, "arducam", 1, 1, 1, object())
            newest = FramePacket("mission-00000000-0000-0000-0000-000000000010", 1, 2, "arducam", 2, 2, 2, object())
            try:
                worker.submit(first)
                worker.submit(newest)
                self.assertEqual(worker.dropped_oldest, 1)
                self.assertEqual(worker.queue.get_nowait().frame_id, 2)
            finally:
                worker.close()

    def test_detector_initialization_failure_isolated_from_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint, manifest = self._write_test_manifest(temporary)
            args = parse_args([
                "--host", "127.0.0.1", "--weights", str(checkpoint),
                "--model-manifest", str(manifest),
            ])
            with patch(
                "jetson.arducam_split_pipeline.DetectionRunner",
                side_effect=RuntimeError("CUDA unavailable"),
            ):
                worker = DetectionWorker(args, Path(temporary), time.time())
            packet = FramePacket(
                "mission-00000000-0000-0000-0000-000000000011",
                1, 0, "arducam", 1, 1, 0, None,
            )
            try:
                self.assertEqual(worker.status, "FAILED")
                worker.start()
                worker.submit(packet)
                deadline = time.time() + 2
                while worker.detections_path.stat().st_size == 0 and time.time() < deadline:
                    time.sleep(0.01)
            finally:
                worker.close()
            payload = json.loads(worker.detections_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(payload["detector"]["status"], "FAILED")
            self.assertEqual(payload["coordinate"], {"status": "not_available"})


if __name__ == "__main__":
    unittest.main()
