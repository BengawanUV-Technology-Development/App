import json
import os
import sys
import unittest
from unittest.mock import patch
from urllib.request import Request

from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.routes.recording import init_recording_routes, recording_bp  # noqa: E402
from app.services.jetson_recording import JetsonRecordingClient  # noqa: E402


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class _FakeCamera:
    port = 5000

    def __init__(self):
        self.running = False

    def start(self):
        self.running = True
        return self.status()

    def stop(self):
        self.running = False
        return self.status()

    def status(self):
        return {
            "camera_status": "RUNNING" if self.running else "STOPPED",
            "camera_running": self.running,
        }


class _FakeJetson:
    def __init__(self):
        self.recording = False
        self.source = "digital"

    def status(self):
        return {
            "ok": True,
            "recording": self.recording,
            "status": "RECORDING" if self.recording else "IDLE",
            "preview_active_source": self.source,
        }

    def preview_source(self):
        return {"ok": True, "preview_source": self.source, "preview_analog_available": True}

    def set_preview_source(self, source):
        self.source = source
        return self.status()

    def start(self, label, video_port, api_port):
        self.recording = True
        return self.status() | {"label": label, "video_port": video_port, "api_port": api_port}

    def stop(self):
        self.recording = False
        return self.status()


class JetsonRecordingTests(unittest.TestCase):
    def test_client_sends_bearer_token_and_json(self):
        client = JetsonRecordingClient("http://jetson:5101/", "secret", timeout=1)
        with patch(
            "app.services.jetson_recording.urlopen",
            return_value=_Response({"ok": True, "recording": False}),
        ) as mocked:
            result = client.set_preview_source("analog")

        request = mocked.call_args.args[0]
        self.assertEqual(result["ok"], True)
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(json.loads(request.data), {"source": "analog"})

    def test_camera_source_switch_auto_opens_receiver(self):
        camera = _FakeCamera()
        jetson = _FakeJetson()
        init_recording_routes(camera, jetson)
        app = Flask(__name__)
        app.register_blueprint(recording_bp)

        with app.test_client() as client:
            response = client.post("/api/v1/camera/source", json={"source": "analog"})

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["source"], "analog")
        self.assertEqual(payload["camera"]["camera_status"], "RUNNING")

    def test_recording_stop_auto_closes_receiver(self):
        camera = _FakeCamera()
        jetson = _FakeJetson()
        init_recording_routes(camera, jetson)
        app = Flask(__name__)
        app.register_blueprint(recording_bp)

        with app.test_client() as client:
            start = client.post("/api/v1/recordings/start", json={"source": "csi"})
            stop = client.post("/api/v1/recordings/stop")

        self.assertEqual(start.status_code, 202)
        self.assertTrue(start.get_json()["recording"])
        self.assertEqual(stop.status_code, 200)
        self.assertFalse(stop.get_json()["recording"])
        self.assertEqual(stop.get_json()["camera"]["camera_status"], "STOPPED")
