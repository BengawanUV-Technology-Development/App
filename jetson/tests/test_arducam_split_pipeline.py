import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jetson.arducam_split_pipeline import DetectionWorker


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
