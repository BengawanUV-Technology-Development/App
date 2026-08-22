import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault(
    "SESSION_LOG_DIR",
    tempfile.mkdtemp(prefix="readonly-backend-logs-"),
)

from main import app, state_manager  # noqa: E402


class HttpSmokeTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        state_manager.update(connected=False, status="OFFLINE", error=None)

    def test_health_endpoint_returns_udp_source(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("connected", payload)
        self.assertEqual(payload["system_address"], "udpin://127.0.0.1:14551")

    def test_telemetry_endpoint_returns_json(self):
        response = self.client.get("/telemetry")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("connected", payload)
        self.assertEqual(payload["source"], "mavlink-udp-readonly")

    def test_capabilities_declare_qgc_as_control_owner(self):
        response = self.client.get("/capabilities")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["control_owner"], "QGroundControl")
        self.assertFalse(payload["commands"]["enabled"])
        self.assertFalse(payload["missions"]["enabled"])
        self.assertEqual(payload["telemetry"]["port"], 14551)

    def test_every_command_endpoint_is_blocked(self):
        requests = [
            ("POST", "/command/connection", {}),
            ("GET", "/command/list_ports", None),
            ("POST", "/command/arm", None),
            ("POST", "/command/disarm", None),
            ("POST", "/command/takeoff", {"altitude_m": 10}),
            ("POST", "/command/land", None),
            ("POST", "/command/set_takeoff_altitude", {"altitude_m": 10}),
            ("POST", "/command/set_flight_mode", {"flight_mode": "AUTO"}),
            ("POST", "/command/reboot", None),
            ("GET", "/command/param?name=SYSID_THISMAV", None),
            ("POST", "/command/param", {"name": "X", "value": 1}),
            ("POST", "/command/force_arm", None),
            ("POST", "/command/disable_rc_check", None),
        ]

        for method, path, payload in requests:
            with self.subTest(method=method, path=path):
                response = self.client.open(method=method, path=path, json=payload)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["error_code"], "READ_ONLY")

    def test_every_mission_endpoint_is_blocked(self):
        requests = [
            ("POST", "/mission/upload", {"waypoints": []}),
            ("POST", "/mission/start", None),
            ("POST", "/mission/pause", None),
            ("POST", "/mission/clear", None),
            ("GET", "/mission/progress", None),
        ]

        for method, path, payload in requests:
            with self.subTest(method=method, path=path):
                response = self.client.open(method=method, path=path, json=payload)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["error_code"], "READ_ONLY")


if __name__ == "__main__":
    unittest.main()
