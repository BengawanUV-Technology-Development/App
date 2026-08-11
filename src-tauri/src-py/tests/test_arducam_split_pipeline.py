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
    def test_default_pipeline_has_independent_highres_and_network_branches(self):
        args = parse_args(["--host", "100.64.0.10"])

        description = build_pipeline_description(args, Path("/tmp/video.mp4"))

        self.assertEqual(description.count("x264enc"), 2)
        self.assertIn("width=1920,height=1080", description)
        self.assertIn("width=960,height=540", description)
        self.assertIn("framerate=30/1", description)
        self.assertIn("framerate=15/1", description)
        self.assertIn("nvvidconv flip-method=2", description)
        self.assertIn("appsink name=highres_sink", description)
        self.assertIn("max-size-buffers=16", description)
        self.assertIn("drop=false", description)
        self.assertIn("rtph264pay pt=96", description)
        self.assertIn("fragment-duration=1000", description)
        self.assertIn("fragment-mode=first-moov-then-finalise", description)
        self.assertIn("moov-recovery-file=\"/tmp/video.mp4.moov.recovery\"", description)
        self.assertIn("appsink name=network_sink", description)
        self.assertIn("input-selector name=preview_selector", description)
        self.assertIn("preview_selector.sink_0", description)
        self.assertNotIn("v4l2src", description)
        self.assertNotIn("preview_selector.sink_1", description)
        self.assertNotIn("udpsink", description)
        self.assertIn("filesink location=\"/tmp/video.mp4\"", description)

    def test_pipeline_orientation_can_be_disabled_explicitly(self):
        args = parse_args(["--host", "100.64.0.10", "--flip-method", "0"])

        description = build_pipeline_description(args, Path("/tmp/video.mp4"))

        self.assertIn("nvvidconv flip-method=0", description)

    def test_invalid_flip_method_is_rejected(self):
        args = parse_args(["--host", "100.64.0.10", "--flip-method", "8"])

        with self.assertRaisesRegex(ValueError, "flip-method"):
            build_pipeline_description(args, Path("/tmp/video.mp4"))

    def test_easycap_is_only_added_to_the_preview_selector(self):
        args = parse_args(
            [
                "--host",
                "100.64.0.10",
                "--easycap-device",
                "/dev/v4l/by-id/easycap-test",
            ]
        )

        description = build_pipeline_description(args, Path("/tmp/video.mp4"))

        self.assertIn('v4l2src device="/dev/v4l/by-id/easycap-test"', description)
        self.assertIn("image/jpeg,width=640,height=480,framerate=30/1", description)
        self.assertIn("jpegparse ! jpegdec ! videoconvert ! videorate", description)
        self.assertIn("tee name=analog_capture", description)
        self.assertIn("jpegenc quality=90 ! jpegparse ! avimux", description)
        self.assertIn("avimux", description)
        self.assertIn('filesink location="/tmp/video_analog.avi"', description)
        self.assertIn("jpegdec", description)
        self.assertNotIn("videoflip", description)
        self.assertIn("videoscale add-borders=true", description)
        self.assertIn("preview_selector.sink_1", description)
        self.assertEqual(description.count("filesink location="), 2)
        self.assertEqual(description.count("appsink name=highres_sink"), 1)

    def test_easycap_device_must_be_an_absolute_path(self):
        args = parse_args(["--host", "100.64.0.10", "--easycap-device", "video2"])

        with self.assertRaisesRegex(ValueError, "absolute"):
            build_pipeline_description(args, Path("/tmp/video.mp4"))

    def test_analog_recording_validation_accepts_avi_header(self):
        pipeline = SplitPipeline.__new__(SplitPipeline)
        pipeline.args = parse_args(
            ["--host", "100.64.0.10", "--easycap-device", "/dev/video1"]
        )
        path = Path("/tmp/test-video-analog.avi")
        try:
            path.write_bytes(b"RIFF\x10\x00\x00\x00AVI payload")
            pipeline.analog_video_path = path

            self.assertIsNone(pipeline._validate_analog_video_output())
        finally:
            path.unlink(missing_ok=True)

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
