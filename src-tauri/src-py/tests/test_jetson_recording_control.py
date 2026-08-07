import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jetson.recording_agent import RecordingController  # noqa: E402
from app.services.jetson_recording_client import JetsonRecordingClient  # noqa: E402
from app.services.flight_recorder import FlightRecorder, FlightRecorderError  # noqa: E402


class FakeProcess:
    pid = 4242

    def __init__(self):
        self.returncode = None
        self.signal = None

    def poll(self):
        return self.returncode

    def send_signal(self, value):
        self.signal = value

    def wait(self, timeout=None):
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9


class JetsonRecordingControlTests(unittest.TestCase):
    def test_agent_starts_one_pipeline_and_stops_it_gracefully(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = FakeProcess()
            config = SimpleNamespace(
                record_dir=Path(temporary),
                pipeline_script=Path(__file__),
                command=lambda session_id, label: ["python3", "pipeline", session_id, label or ""],
            )
            controller = RecordingController(config)

            with patch("jetson.recording_agent.subprocess.Popen", return_value=process) as popen:
                started = controller.start("survey")
                active = controller.start("ignored")
                stopped = controller.stop()

            self.assertTrue(started["recording"])
            self.assertEqual(active["session_id"], started["session_id"])
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(stopped["status"], "COMPLETED")
            self.assertFalse(stopped["recording"])

    def test_gcs_client_reports_unconfigured_agent_explicitly(self):
        client = JetsonRecordingClient()
        client.base_url = ""

        state = client.status()

        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "REMOTE_UNCONFIGURED")

    def test_jetson_flight_recorder_does_not_fall_back_to_gcs_video(self):
        with patch.dict(
            "os.environ",
            {"CAMERA_SOURCE": "jetson_udp", "JETSON_RECORDING_AGENT_URL": ""},
            clear=False,
        ):
            recorder = FlightRecorder(lambda: {})
            self.assertEqual(recorder.status()["status"], "REMOTE_UNCONFIGURED")
            with patch.object(recorder, "start_camera", return_value={}):
                with self.assertRaisesRegex(FlightRecorderError, "JETSON_RECORDING_AGENT_URL"):
                    recorder.start()

if __name__ == "__main__":
    unittest.main()
