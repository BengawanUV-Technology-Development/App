import os
import time
import unittest
from unittest.mock import patch

from app.services.jetson_video_service import JpegFrameParser, JetsonVideoService


class JpegFrameParserTests(unittest.TestCase):
    def test_extracts_frames_split_across_chunks(self):
        parser = JpegFrameParser()
        first = b"noise\xff\xd8frame-one\xff\xd9"
        second = b"\xff\xd8frame-two\xff\xd9tail"

        self.assertEqual(parser.feed(first[:7]), [])
        self.assertEqual(parser.feed(first[7:] + second[:5]), [b"\xff\xd8frame-one\xff\xd9"])
        self.assertEqual(parser.feed(second[5:]), [b"\xff\xd8frame-two\xff\xd9"])

    def test_discards_unbounded_broken_frame(self):
        parser = JpegFrameParser(max_frame_bytes=8)
        self.assertEqual(parser.feed(b"\xff\xd8" + b"x" * 20), [])
        self.assertEqual(parser.feed(b"\xff\xd8ok\xff\xd9"), [b"\xff\xd8ok\xff\xd9"])


class JetsonVideoServiceTests(unittest.TestCase):
    def test_pipeline_matches_sender_contract(self):
        env = {
            "JETSON_VIDEO_BIND_ADDRESS": "0.0.0.0",
            "JETSON_VIDEO_PORT": "5000",
            "JETSON_VIDEO_PAYLOAD_TYPE": "96",
            "JETSON_VIDEO_PREVIEW_WIDTH": "1280",
            "JETSON_VIDEO_PREVIEW_HEIGHT": "720",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "app.services.jetson_video_service.shutil.which",
            return_value="/usr/bin/gst-launch-1.0",
        ):
            service = JetsonVideoService()
            command = service.build_pipeline()

        command_text = " ".join(command)
        self.assertIn("udpsrc address=0.0.0.0 port=5000", command_text)
        self.assertIn("payload=96", command_text)
        self.assertIn("rtpjitterbuffer", command)
        self.assertIn("rtph264depay", command)
        self.assertIn("avdec_h264", command)
        self.assertIn("fdsink", command)

    def test_initial_status_is_stopped_and_explicit(self):
        with patch(
            "app.services.jetson_video_service.shutil.which",
            return_value="/usr/bin/gst-launch-1.0",
        ):
            service = JetsonVideoService()
            state = service.status()

        self.assertEqual(state["camera_source"], "jetson_udp")
        self.assertEqual(state["camera_status"], "STOPPED")
        self.assertEqual(state["stream_port"], None)

    def test_live_stream_becomes_stale_after_frame_timeout(self):
        with patch.dict(os.environ, {"JETSON_VIDEO_FRAME_TIMEOUT_SECONDS": "0.5"}, clear=False), patch(
            "app.services.jetson_video_service.shutil.which",
            return_value="/usr/bin/gst-launch-1.0",
        ):
            service = JetsonVideoService()
            with service._lock:
                service._camera_state.update(
                    camera_status="LIVE",
                    camera_running=True,
                    last_frame_at_unix=time.time() - 1,
                )
            state = service.status()

        self.assertEqual(state["camera_status"], "STALE")
        self.assertIn("No decoded frame", state["camera_error"])


if __name__ == "__main__":
    unittest.main()
