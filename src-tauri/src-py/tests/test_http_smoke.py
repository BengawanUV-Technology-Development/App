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
import app.routes.mission as mission_module
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

    async def execute_set_flight_mode(self, mode):
        return {
            "ok": True,
            "command": "set_flight_mode",
            "command_id": "smoke-flight-mode",
            "ts": 1.0,
            "message": f"Flight mode transition requested: {mode}",
        }

    async def execute_reboot(self):
        return {
            "ok": True,
            "command": "reboot",
            "command_id": "smoke-reboot",
            "ts": 1.0,
            "message": "Reboot requested successfully",
        }


class FakeMissionService:
    async def execute_upload_mission(self, waypoints):
        return {
            "ok": True,
            "command": "mission_upload",
            "command_id": "smoke-mission-upload",
            "ts": 1.0,
            "message": f"Mission uploaded with {len(waypoints)} waypoints",
        }

    async def execute_start_mission(self):
        return {
            "ok": True,
            "command": "mission_start",
            "command_id": "smoke-mission-start",
            "ts": 1.0,
            "message": "Mission start requested",
        }

    async def execute_pause_mission(self):
        return {
            "ok": True,
            "command": "mission_pause",
            "command_id": "smoke-mission-pause",
            "ts": 1.0,
            "message": "Mission pause requested",
        }

    async def execute_clear_mission(self):
        return {
            "ok": True,
            "command": "mission_clear",
            "command_id": "smoke-mission-clear",
            "ts": 1.0,
            "message": "Mission clear requested",
        }

    async def execute_mission_progress(self):
        return {
            "ok": True,
            "command": "mission_progress",
            "command_id": "smoke-mission-progress",
            "ts": 1.0,
            "current": 1,
            "total": 3,
        }


class HttpSmokeTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.previous_service = commands_module._command_service
        self.previous_mission_service = mission_module._mission_service
        commands_module._command_service = FakeCommandService()
        mission_module._mission_service = FakeMissionService()
        state_manager.update(connected=True, error=None)

    def tearDown(self):
        commands_module._command_service = self.previous_service
        mission_module._mission_service = self.previous_mission_service

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

    def test_set_flight_mode_endpoint_uses_command_contract(self):
        response = self.client.post(
            "/command/set_flight_mode",
            json={"mode": "Q_HOVER"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "set_flight_mode")

    def test_set_flight_mode_invalid_request_uses_error_contract(self):
        class InvalidModeService:
            async def execute_set_flight_mode(self, mode):
                raise InvalidRequestError("mode not supported")

        commands_module._command_service = InvalidModeService()

        response = self.client.post(
            "/command/set_flight_mode",
            json={"mode": "Q_STABILIZE"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "INVALID_REQUEST")

    def test_reboot_endpoint_uses_command_contract(self):
        response = self.client.post("/command/reboot")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "reboot")

    def test_reboot_invalid_request_uses_error_contract(self):
        class InvalidRebootService:
            async def execute_reboot(self):
                raise InvalidRequestError("reboot disallowed")

        commands_module._command_service = InvalidRebootService()

        response = self.client.post("/command/reboot")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "INVALID_REQUEST")

    def test_mission_upload_endpoint_uses_command_contract(self):
        response = self.client.post(
            "/mission/upload",
            json={
                "waypoints": [
                    {
                        "seq": 0,
                        "latitude_deg": -6.2,
                        "longitude_deg": 106.8,
                        "relative_altitude_m": 10,
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "mission_upload")

    def test_mission_progress_endpoint_uses_command_contract(self):
        response = self.client.get("/mission/progress")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "mission_progress")
        self.assertEqual(payload["current"], 1)
        self.assertEqual(payload["total"], 3)


if __name__ == "__main__":
    unittest.main()
