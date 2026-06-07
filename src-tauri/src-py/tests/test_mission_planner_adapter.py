import time
import unittest

import app.routes.api_v1 as api_v1_module
from app.services.mission_planner_adapter import MissionPlannerAdapter, MissionPlannerBridgeError
from main import app


VALID_TELEMETRY = {
    "ok": True,
    "timestamp": time.time(),
    "source": "mission-planner",
    "vehicle": {"connected": True, "armed": False, "flight_mode": "QHOVER"},
    "position": {
        "lat": -7.553,
        "lng": 110.865,
        "relative_alt_m": 10.0,
        "absolute_alt_m": None,
        "gps_status": 6,
        "gps_hdop": 1.2,
        "satellites": 10,
    },
    "attitude": {"roll_deg": 1.0, "pitch_deg": 2.0, "yaw_deg": 3.0, "heading_deg": 3.0},
    "velocity": {"airspeed_m_s": 4.0, "groundspeed_m_s": 5.0, "vertical_speed_m_s": 0.5},
    "battery": {"remaining_percent": 99.0, "voltage_v": 12.6, "current_a": 0.0},
}

VALID_MISSION = {
    "ok": True,
    "timestamp": time.time(),
    "source": "mission-planner",
    "count": 3,
    "waypoints": [
        {"index": 0, "seq": 0, "command": 16, "command_name": "WAYPOINT", "frame": 3, "lat": -7.553, "lng": 110.865, "alt_m": 0},
        {"index": 1, "seq": 1, "command": 22, "command_name": "TAKEOFF", "frame": 3, "lat": -7.552, "lng": 110.866, "alt_m": 30},
        {"index": 2, "seq": 2, "command": 20, "command_name": "RTL", "frame": 3, "lat": None, "lng": None, "alt_m": None},
    ],
}


class FakeMissionPlannerAdapter(MissionPlannerAdapter):
    def __init__(self, response=None, error=None):
        super().__init__(stale_after_seconds=2.0)
        self.response = response
        self.error = error

    def _request_json(self, path, method="GET", payload=None):
        if self.error:
            raise RuntimeError(self.error)
        return 200, self.response


class MissionPlannerAdapterTests(unittest.TestCase):
    def test_poll_normalizes_bridge_telemetry(self):
        adapter = FakeMissionPlannerAdapter(response=VALID_TELEMETRY)

        snapshot = adapter.poll_once()

        self.assertFalse(snapshot["stale"])
        self.assertTrue(snapshot["gps_valid"])
        self.assertEqual(snapshot["telemetry"]["flight_mode"], "QHOVER")
        self.assertEqual(snapshot["telemetry"]["alt"], 10.0)
        self.assertEqual(snapshot["telemetry"]["battery_percent"], 99.0)

    def test_zero_coordinates_are_not_valid_gps(self):
        raw = {**VALID_TELEMETRY, "position": {**VALID_TELEMETRY["position"], "lat": 0.0, "lng": 0.0}}
        adapter = FakeMissionPlannerAdapter(response=raw)

        snapshot = adapter.poll_once()

        self.assertFalse(snapshot["gps_valid"])

    def test_connected_stream_with_unknown_zero_state_is_not_command_ready(self):
        raw = {
            **VALID_TELEMETRY,
            "vehicle": {"connected": True, "armed": False, "flight_mode": "Unknown"},
            "position": {**VALID_TELEMETRY["position"], "lat": 0.0, "lng": 0.0, "gps_status": 0, "satellites": 0},
            "battery": {**VALID_TELEMETRY["battery"], "voltage_v": 0.0, "remaining_percent": 0.0},
        }
        adapter = FakeMissionPlannerAdapter(response=raw)

        snapshot = adapter.poll_once()

        self.assertFalse(snapshot["telemetry"]["connected"])
        self.assertFalse(snapshot["telemetry"]["state_valid"])
        self.assertEqual(snapshot["telemetry"]["status"], "VEHICLE_STATE_UNAVAILABLE")

    def test_bridge_failure_reports_offline_without_crashing(self):
        adapter = FakeMissionPlannerAdapter(error="connection refused")

        snapshot = adapter.poll_once()

        self.assertTrue(snapshot["stale"])
        self.assertFalse(snapshot["bridge"]["online"])
        self.assertEqual(snapshot["telemetry"]["status"], "BRIDGE_OFFLINE")
        self.assertIn("connection refused", snapshot["telemetry"]["error"])

    def test_old_success_becomes_stale(self):
        adapter = FakeMissionPlannerAdapter(response=VALID_TELEMETRY)
        adapter.poll_once()
        adapter._telemetry["last_update"] = time.time() - 5

        snapshot = adapter.snapshot()

        self.assertTrue(snapshot["stale"])
        self.assertEqual(snapshot["telemetry"]["status"], "STALE")

    def test_mission_normalizes_positioned_and_non_positioned_waypoints(self):
        adapter = FakeMissionPlannerAdapter(response=VALID_MISSION)

        mission = adapter.mission()

        self.assertEqual(mission["count"], 3)
        self.assertEqual(mission["positioned_count"], 2)
        self.assertTrue(mission["waypoints"][0]["has_position"])
        self.assertFalse(mission["waypoints"][2]["has_position"])


class FakeApiAdapter:
    reject_reboot = False

    def health(self):
        return {"ok": True, "status": "ACTIVE", "connected": True, "stale": False}

    def snapshot(self):
        return {"ok": True, "stale": False, "gps_valid": True, "telemetry": {"flight_mode": "QHOVER"}}

    def mission(self):
        return MissionPlannerAdapter._normalize_mission(VALID_MISSION)

    def send_command(self, command, payload):
        if command == "reboot" and self.reject_reboot:
            raise MissionPlannerBridgeError(400, {"ok": False, "error": "Reboot is only allowed while vehicle is disarmed"})
        return {"ok": True, "command": command, "mode": payload.get("mode")}, 200


class ApiV1Tests(unittest.TestCase):
    def setUp(self):
        self.previous_adapter = api_v1_module._adapter
        api_v1_module._adapter = FakeApiAdapter()
        self.client = app.test_client()

    def tearDown(self):
        api_v1_module._adapter = self.previous_adapter

    def test_health_and_telemetry_routes(self):
        health = self.client.get("/api/v1/health")
        telemetry = self.client.get("/api/v1/telemetry")

        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.get_json()["connected"])
        self.assertEqual(telemetry.status_code, 200)
        self.assertTrue(telemetry.get_json()["gps_valid"])

    def test_mission_route_proxies_to_bridge(self):
        response = self.client.get("/api/v1/mission")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["positioned_count"], 2)
        self.assertEqual(payload["waypoints"][1]["command_name"], "TAKEOFF")

    def test_set_flight_mode_proxies_to_bridge(self):
        response = self.client.post("/api/v1/commands/set-flight-mode", json={"mode": "Q_HOVER"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(response.get_json()["command"], "set-flight-mode")

    def test_arm_proxies_to_bridge(self):
        response = self.client.post("/api/v1/commands/arm")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["command"], "arm")

    def test_reboot_proxies_to_bridge(self):
        response = self.client.post("/api/v1/commands/reboot")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["command"], "reboot")

    def test_bridge_command_rejection_keeps_status_and_message(self):
        api_v1_module._adapter.reject_reboot = True
        response = self.client.post("/api/v1/commands/reboot")
        api_v1_module._adapter.reject_reboot = False

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Reboot is only allowed while vehicle is disarmed")

if __name__ == "__main__":
    unittest.main()
