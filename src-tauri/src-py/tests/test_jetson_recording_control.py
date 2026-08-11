import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jetson.recording_agent import (  # noqa: E402
    AgentConfig,
    RecordingAgentError,
    RecordingController,
)
from jetson.mission_storage import MissionCatalog, MissionStorageError  # noqa: E402
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
    def test_mission_epochs_are_durable_and_fail_after_three_capture_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = MissionCatalog(temporary)
            mission_id, epoch, _ = catalog.allocate(label="survey")
            self.assertEqual(epoch, 1)
            catalog.finalize_epoch(mission_id, epoch, "FAILED", "capture error 1")
            for expected in (2, 3):
                same_id, epoch, _ = MissionCatalog(temporary).allocate(mission_id)
                self.assertEqual((same_id, epoch), (mission_id, expected))
                catalog.finalize_epoch(mission_id, epoch, "FAILED", f"capture error {expected}")
            with self.assertRaisesRegex(MissionStorageError, "FAILED"):
                catalog.allocate(mission_id)

    def test_agent_config_allows_runtime_gcs_without_env_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = {
                "JETSON_RECORDING_AGENT_TOKEN": "test-token",
                "JETSON_INGEST_TOKEN": "test-ingest-token",
                "JETSON_RECORDING_PIPELINE_SCRIPT": str(Path(__file__)),
                "JETSON_RECORD_DIR": temporary,
            }
            with patch.dict("os.environ", env, clear=True):
                config = AgentConfig()
                command = config.command(
                    "flight-test",
                    None,
                    gcs_host="100.87.201.110",
                    video_port=5010,
                    api_port=5002,
                )

        self.assertIsNone(config.gcs_host)
        self.assertEqual(command[command.index("--host") + 1], "100.87.201.110")
        self.assertEqual(command[command.index("--port") + 1], "5010")
        self.assertEqual(command[command.index("--capture-epoch") + 1], "1")
        self.assertEqual(command[command.index("--ingest-token") + 1], "test-ingest-token")
        self.assertEqual(
            command[command.index("--ingest-url") + 1],
            "http://100.87.201.110:5002/api/v1/detection/overlay",
        )

    def test_agent_starts_one_pipeline_and_stops_it_gracefully(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = FakeProcess()
            config = SimpleNamespace(
                record_dir=Path(temporary),
                pipeline_script=Path(__file__),
                gcs_host="100.64.0.20",
                video_port=5000,
                gcs_api_port=5001,
                command=lambda session_id, label, **_runtime: [
                    "python3", "pipeline", session_id, label or ""
                ],
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
            controller.shutdown()

    def test_agent_uses_request_source_as_runtime_gcs_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = FakeProcess()
            command_args = {}

            def build_command(session_id, label, **runtime):
                command_args.update(runtime)
                return ["python3", "pipeline", session_id]

            config = SimpleNamespace(
                record_dir=Path(temporary),
                pipeline_script=Path(__file__),
                gcs_host="100.64.0.20",
                video_port=5000,
                gcs_api_port=5001,
                allow_gcs_host_override=False,
                command=build_command,
            )
            controller = RecordingController(config)

            with patch("jetson.recording_agent.subprocess.Popen", return_value=process):
                started = controller.start(
                    "survey",
                    request_host="100.87.201.110",
                    video_port=5010,
                    api_port=5002,
                )

            self.assertEqual(command_args["gcs_host"], "100.87.201.110")
            self.assertEqual(command_args["video_port"], 5010)
            self.assertEqual(command_args["api_port"], 5002)
            self.assertEqual(
                started["stream_target"],
                {"host": "100.87.201.110", "video_port": 5010, "api_port": 5002},
            )
            controller.stop()
            controller.shutdown()

    def test_agent_rejects_redirect_to_another_host_by_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = SimpleNamespace(
                record_dir=Path(temporary),
                pipeline_script=Path(__file__),
                gcs_host=None,
                video_port=5000,
                gcs_api_port=5001,
                allow_gcs_host_override=False,
                command=lambda session_id, label, **_runtime: ["python3", "pipeline"],
            )
            controller = RecordingController(config)

            with self.assertRaisesRegex(
                RecordingAgentError, "override does not match the request source"
            ):
                controller.start(
                    request_host="100.87.201.110",
                    gcs_host="100.87.201.111",
                )
            controller.shutdown()

    def test_gcs_client_reports_unconfigured_agent_explicitly(self):
        client = JetsonRecordingClient()
        client.base_url = ""

        state = client.status()

        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "REMOTE_UNCONFIGURED")

    def test_gcs_client_does_not_claim_idle_when_jetson_is_unreachable(self):
        client = JetsonRecordingClient()
        client.base_url = "http://jetson.test:5101"

        with patch(
            "app.services.jetson_recording_client.urlopen",
            side_effect=OSError("network is down"),
        ):
            state = client.status()

        self.assertIsNone(state["recording"])
        self.assertEqual(state["status"], "REMOTE_UNKNOWN")
        self.assertFalse(state["state_known"])

    def test_gcs_client_sends_runtime_receiver_ports(self):
        with patch.dict("os.environ", {"API_PORT": "5002"}, clear=False):
            client = JetsonRecordingClient()
        client.base_url = "http://jetson.test:5101"

        with patch.object(client, "_request", return_value={"ok": True}) as request:
            client.start("survey", video_port=5010)

        request.assert_called_once_with(
            "/recording/start",
            "POST",
            {"label": "survey", "api_port": 5002, "video_port": 5010},
        )

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
