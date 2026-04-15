import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VENV_SITE_PACKAGES = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
if VENV_SITE_PACKAGES.exists() and str(VENV_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(VENV_SITE_PACKAGES))

import app.routes.commands as commands_module
from main import app, state_manager


class FakeCommandService:
    async def execute_arm(self):
        return {
            "ok": True,
            "command": "arm",
            "command_id": "smoke-arm",
            "ts": 1.0,
            "message": "Vehicle armed successfully",
        }

    async def execute_takeoff(self, altitude_m):
        return {
            "ok": True,
            "command": "takeoff",
            "command_id": "smoke-takeoff",
            "ts": 1.0,
            "message": f"Takeoff initiated to {float(altitude_m)} meters",
        }


class HttpSmokeTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.previous_service = commands_module._command_service
        commands_module._command_service = FakeCommandService()
        state_manager.update(connected=True, error=None)

    def tearDown(self):
        commands_module._command_service = self.previous_service

    def test_health_endpoint_returns_json(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("connected", payload)
        self.assertIn("system_address", payload)

    def test_telemetry_endpoint_returns_json(self):
        response = self.client.get("/telemetry")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("connected", payload)
        self.assertIn("error", payload)

    def test_arm_command_endpoint_uses_command_contract(self):
        response = self.client.post("/command/arm")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "arm")

    def test_takeoff_command_endpoint_uses_command_contract(self):
        response = self.client.post(
            "/command/takeoff",
            json={"altitude_m": 10},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "takeoff")


if __name__ == "__main__":
    unittest.main()
