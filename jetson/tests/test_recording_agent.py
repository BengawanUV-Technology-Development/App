import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jetson.recording_agent import AgentConfig, RecordingController


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
        self.camera_release_wait_seconds = 0

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
    def test_inference_dimensions_and_rate_are_forwarded_to_child_pipeline(self):
        pipeline_script = Path(__file__).resolve().parents[1] / "arducam_split_pipeline.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            environment = {
                "JETSON_RECORDING_AGENT_TOKEN": "agent-token",
                "JETSON_INGEST_TOKEN": "ingest-token",
                "JETSON_GCS_HOST": "127.0.0.1",
                "JETSON_RECORDING_PIPELINE_SCRIPT": str(pipeline_script),
                "JETSON_INFERENCE_PYTHON": sys.executable,
                "JETSON_RECORD_DIR": temp_dir,
                "JETSON_INFERENCE_WIDTH": "1280",
                "JETSON_INFERENCE_HEIGHT": "720",
                "JETSON_INFERENCE_FPS": "15",
            }
            with patch.dict(os.environ, environment, clear=True):
                config = AgentConfig()

            command = config.command(
                "mission-55555555-5555-4555-8555-555555555555",
                None,
            )

        self.assertIn("--inference-width", command)
        self.assertEqual(command[command.index("--inference-width") + 1], "1280")
        self.assertEqual(command[command.index("--inference-height") + 1], "720")
        self.assertEqual(command[command.index("--inference-fps") + 1], "15.0")

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

    def test_waits_for_preview_camera_release_before_pipeline_spawn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            record_dir = Path(temp_dir)
            config = _FakeConfig(record_dir)
            config.camera_release_wait_seconds = 0.25
            controller = RecordingController(config)
            marker = record_dir / ".recording-agent.active.json"
            events = []

            def assert_marker_before_spawn(*_args, **_kwargs):
                events.append("spawn")
                self.assertTrue(marker.exists())
                self.assertEqual(events[0], "marker")
                self.assertEqual(events[1][0], "wait")
                return _FakeProcess()

            def record_marker():
                events.append("marker")
                marker.write_text("{}", encoding="utf-8")

            try:
                with patch.object(controller, "_write_active_state", side_effect=record_marker):
                    with patch(
                        "jetson.recording_agent.time.sleep",
                        side_effect=lambda seconds: events.append(("wait", seconds)),
                    ):
                        with patch(
                            "jetson.recording_agent.subprocess.Popen",
                            side_effect=assert_marker_before_spawn,
                        ):
                            result = controller.start(
                                mission_id="mission-44444444-4444-4444-8444-444444444444"
                            )
            finally:
                controller._release_lock()

            self.assertTrue(result["recording"])
            self.assertEqual(events[1], ("wait", 0.25))


if __name__ == "__main__":
    unittest.main()
