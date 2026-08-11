import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jetson.arducam_split_pipeline import (  # noqa: E402
    RtpNetworkSender,
    SplitPipeline,
    build_pipeline_description,
    parse_args,
    scale_bbox,
)


class ArducamSplitPipelineTests(unittest.TestCase):
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
        self.assertIn("rtph264pay pt=96", description)
        self.assertIn("fragment-duration=1000", description)
        self.assertIn("fragment-mode=first-moov-then-finalise", description)
        self.assertIn("moov-recovery-file=\"/tmp/video.mp4.moov.recovery\"", description)
        self.assertIn("appsink name=network_sink", description)
        self.assertNotIn("udpsink", description)
        self.assertIn("filesink location=\"/tmp/video.mp4\"", description)

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


if __name__ == "__main__":
    unittest.main()
