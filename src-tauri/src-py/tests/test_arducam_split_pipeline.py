import sys
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jetson.arducam_split_pipeline import (  # noqa: E402
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
        self.assertIn("appsink name=highres_sink", description)
        self.assertIn("max-size-buffers=16", description)
        self.assertIn("drop=false", description)
        self.assertIn("rtph264pay pt=96", description)
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


if __name__ == "__main__":
    unittest.main()
