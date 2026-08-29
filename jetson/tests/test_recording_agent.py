import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jetson.recording_agent import RecordingController


class _FakeConfig:
    def __init__(self, record_dir: Path):
        self.record_dir = record_dir
        self.storage_guard = False
        self.record_mountpoint = None
        self.allow_root_record_dir = False
        self.gcs_host = "127.0.0.1"
        self.allow_gcs_host_override = False
        self.video_port = 5000
        self.gcs_api_port = 5001
        self.easycap_device = ""
        self.pipeline_script = record_dir / "arducam_split_pipeline.py"
        self.stop_timeout_seconds = 10

    def command(self, *_args, **_kwargs):
        return ["fake-pipeline"]

    def pipeline_environment(self):
        return {}


class _FakeProcess:
    pid = 4242

    @staticmethod
    def poll():
        return None


class RecordingAgentTests(unittest.TestCase):
    def test_active_marker_exists_before_pipeline_spawn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            record_dir = Path(temp_dir)
            config = _FakeConfig(record_dir)
            controller = RecordingController(config)
            marker = record_dir / ".recording-agent.active.json"

            def assert_marker_before_spawn(*_args, **_kwargs):
                self.assertTrue(marker.exists())
                payload = json.loads(marker.read_text(encoding="utf-8"))
                self.assertIsNone(payload["pid"])
                return _FakeProcess()

            try:
                with patch(
                    "jetson.recording_agent.subprocess.Popen",
                    side_effect=assert_marker_before_spawn,
                ):
                    result = controller.start(
                        mission_id="mission-33333333-3333-4333-8333-333333333333"
                    )
            finally:
                controller._release_lock()

            self.assertTrue(result["recording"])
            self.assertEqual(result["pid"], _FakeProcess.pid)


if __name__ == "__main__":
    unittest.main()
