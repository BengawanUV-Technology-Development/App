import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jetson.arducam_split_pipeline as pipeline
from jetson.arducam_split_pipeline import DetectionWorker, build_pipeline_description


def _pipeline_args(**overrides):
    values = {
        "high_width": 3840,
        "high_height": 2160,
        "high_fps": 30.0,
        "network_width": 960,
        "network_height": 540,
        "network_fps": 15.0,
        "inference_width": 960,
        "inference_height": 540,
        "inference_fps": 15.0,
        "host": "127.0.0.1",
        "sensor_id": 0,
        "flip_method": 0,
        "port": 5000,
        "payload_type": 96,
        "rtp_ssrc": 1234,
        "local_bitrate_kbps": 12000,
        "network_bitrate_kbps": 2000,
        "slice_width": 640,
        "slice_height": 640,
        "imgsz": 640,
        "conf": 0.25,
        "ingest_timeout": 0.5,
        "ingest_url": "",
        "event_ingest_url": "",
        "registration_url": "",
        "ingest_token": "",
        "overlap": 0.2,
        "sidecar_queue_size": 4096,
        "eos_timeout_seconds": 30.0,
        "qualification_video": None,
        "allow_qualification_file_source": False,
        "easycap_device": "",
        "easycap_width": 640,
        "easycap_height": 480,
        "easycap_fps": 30.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RealtimeInferencePipelineTests(unittest.TestCase):
    def test_inference_rate_selector_is_independent_of_preview_rate(self):
        selector = getattr(pipeline, "inference_branch_will_carry_frame", None)
        self.assertIsNotNone(selector)

        selected = [
            frame_id
            for frame_id in range(12)
            if selector(frame_id, source_fps=30.0, inference_fps=10.0)
        ]

        self.assertEqual(selected, [0, 3, 6, 9])

    def test_inference_branch_uses_own_scaled_caps_and_identity_probe(self):
        args = _pipeline_args()
        description = build_pipeline_description(args, Path("/tmp/video.mp4"))

        self.assertIn("identity name=inference_identity", description)
        self.assertIn(
            "video/x-raw,format=BGR,width=960,height=540", description
        )
        self.assertNotIn(
            "video/x-raw,format=BGR,width=3840,height=2160", description
        )

    def test_inference_bbox_is_normalized_from_inference_frame_to_master_frame(self):
        normalizer = getattr(pipeline, "normalize_bbox_xyxy", None)
        self.assertIsNotNone(normalizer)

        normalized = normalizer(
            [48.0, 54.0, 480.0, 270.0],
            source_width=960,
            source_height=540,
            target_width=3840,
            target_height=2160,
        )

        self.assertEqual(normalized, [0.05, 0.1, 0.5, 0.5])


class DetectionWorkerStartupTests(unittest.TestCase):
    def test_model_initialization_is_deferred_until_capture_is_running(self):
        args = SimpleNamespace(
            weights="/models/best.pt",
            model_manifest=Path("/models/production.json"),
            device="cpu",
            imgsz=640,
            conf=0.25,
            sahi=False,
            ingest_token="token",
            ingest_timeout=1.0,
            high_width=1920,
            high_height=1080,
            ingest_url=None,
            event_ingest_url=None,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("jetson.arducam_split_pipeline.ProductionModelManifest") as manifest:
                with patch("jetson.arducam_split_pipeline.DetectionRunner") as runner:
                    worker = DetectionWorker(args, Path(temp_dir), time.time())
                    try:
                        self.assertEqual(worker.status, "STARTING")
                        manifest.assert_not_called()
                        runner.assert_not_called()
                    finally:
                        worker.close()


if __name__ == "__main__":
    unittest.main()
