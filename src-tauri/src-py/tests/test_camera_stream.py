import os
import sys
import threading
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.camera_stream import CameraStreamService, CameraStreamError  # noqa: E402


class CameraStreamServiceTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            key: os.environ.get(key)
            for key in (
                "JETSON_VIDEO_BIND_ADDRESS",
                "JETSON_VIDEO_PORT",
                "JETSON_VIDEO_PAYLOAD_TYPE",
                "JETSON_VIDEO_PREVIEW_WIDTH",
                "JETSON_VIDEO_PREVIEW_HEIGHT",
                "JETSON_VIDEO_DECODER",
            )
        }

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_pipeline_matches_reference_rtp_contract(self):
        os.environ["JETSON_VIDEO_BIND_ADDRESS"] = "127.0.0.1"
        os.environ["JETSON_VIDEO_PORT"] = "5005"
        os.environ["JETSON_VIDEO_PAYLOAD_TYPE"] = "97"
        os.environ["JETSON_VIDEO_PREVIEW_WIDTH"] = "1280"
        os.environ["JETSON_VIDEO_PREVIEW_HEIGHT"] = "720"

        service = CameraStreamService()
        pipeline = service.build_pipeline()

        self.assertIn('address="127.0.0.1" port=5005', pipeline)
        self.assertIn("encoding-name=H264,payload=97", pipeline)
        self.assertIn("width=1280,height=720", pipeline)
        self.assertIn("appsink name=jpeg_sink", pipeline)

    def test_invalid_decoder_is_rejected_before_gstreamer_load(self):
        os.environ["JETSON_VIDEO_DECODER"] = "avdec-h264 ! fakesink"
        with self.assertRaises(CameraStreamError):
            CameraStreamService()

    def test_publish_frame_updates_status_and_mjpeg_chunk(self):
        service = CameraStreamService()
        service._publish_frame(b"\xff\xd8fake-jpeg\xff\xd9")

        state = service.status()
        self.assertEqual(state["camera_status"], "RUNNING")
        self.assertEqual(state["frame_count"], 1)
        self.assertEqual(state["transport"], "H264/RTP/UDP")

        # Pretend the receiver thread is already active so this unit test can
        # exercise the MJPEG framing without requiring native GStreamer.
        service._thread = threading.current_thread()
        stream = service.preview_stream()
        chunk = next(stream)
        self.assertTrue(chunk.startswith(b"--frame\r\nContent-Type: image/jpeg"))
        self.assertIn(b"\xff\xd8fake-jpeg\xff\xd9", chunk)
        stream.close()


if __name__ == "__main__":
    unittest.main()
