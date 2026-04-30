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
from app.utils.errors import CommandFailedError, CommandTimeoutError, InvalidRequestError


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

    def test_takeoff_invalid_request_uses_error_contract(self):
        class InvalidTakeoffService:
            async def execute_takeoff(self, altitude_m):
                raise InvalidRequestError("invalid altitude")

        commands_module._command_service = InvalidTakeoffService()

        response = self.client.post(
            "/command/takeoff",
            json={"altitude_m": "abc"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "INVALID_REQUEST")

    def test_arm_timeout_uses_timeout_error_contract(self):
        class TimeoutArmService:
            async def execute_arm(self):
                raise CommandTimeoutError()

        commands_module._command_service = TimeoutArmService()

        response = self.client.post("/command/arm")

        self.assertEqual(response.status_code, 504)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "TIMEOUT")

    def test_disarm_command_failed_uses_error_contract(self):
        class FailedDisarmService:
            async def execute_disarm(self):
                raise CommandFailedError("failed to disarm vehicle")

        commands_module._command_service = FailedDisarmService()

        response = self.client.post("/command/disarm")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "COMMAND_FAILED")

    def test_land_timeout_uses_error_contract(self):
        class TimeoutLandService:
            async def execute_land(self):
                raise CommandTimeoutError()

        commands_module._command_service = TimeoutLandService()

        response = self.client.post("/command/land")

        self.assertEqual(response.status_code, 504)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "TIMEOUT")

    def test_set_takeoff_altitude_invalid_request_uses_error_contract(self):
        class InvalidAltitudeService:
            async def execute_set_takeoff_altitude(self, altitude_m):
                raise InvalidRequestError("invalid altitude")

        commands_module._command_service = InvalidAltitudeService()

        response = self.client.post(
            "/command/set_takeoff_altitude",
            json={"altitude_m": "abc"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
