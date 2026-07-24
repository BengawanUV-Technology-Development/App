"""Development-only fake for the Mission Planner bridge contract."""

import argparse
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeBridgeState:
    started_at = time.time()
    flight_mode = "QHOVER"
    armed = False
    reboot_count = 0
    current_waypoint_seq = None
    mission = [
        {"index": 0, "seq": 0, "command": 16, "command_name": "WAYPOINT", "frame": 3, "lat": -7.7715, "lng": 110.3775, "alt_m": 0.0},
        {"index": 1, "seq": 1, "command": 22, "command_name": "TAKEOFF", "frame": 3, "lat": -7.7712, "lng": 110.3778, "alt_m": 35.0},
        {"index": 2, "seq": 2, "command": 16, "command_name": "WAYPOINT", "frame": 3, "lat": -7.7709, "lng": 110.3782, "alt_m": 45.0},
        {"index": 3, "seq": 3, "command": 16, "command_name": "WAYPOINT", "frame": 3, "lat": -7.7717, "lng": 110.3786, "alt_m": 45.0},
        {"index": 4, "seq": 4, "command": 20, "command_name": "RTL", "frame": 3, "lat": None, "lng": None, "alt_m": None},
    ]
    messages = [
        "AHRS: EKF3 active",
        "EKF3 IMU0 is using GPS",
        "EKF3 IMU0 origin set",
        "Field Elevation Set: 99m",
        "GPS 1: detected u-blox",
        "ArduPlane V4.8.0-dev",
        "Airspeed 1 Calibrated",
    ]

    @classmethod
    def current_seq(cls):
        if cls.current_waypoint_seq is not None:
            return cls.current_waypoint_seq
        return int((time.time() - cls.started_at) / 12.0) % len(cls.mission)

    @classmethod
    def telemetry(cls):
        elapsed = time.time() - cls.started_at
        return {
            "ok": True,
            "timestamp": time.time(),
            "source": "fake-mission-planner",
            "vehicle": {
                "connected": True,
                "armed": cls.armed,
                "flight_mode": cls.flight_mode,
            },
            "position": {
                "lat": -7.7715 + math.sin(elapsed / 20.0) * 0.0002,
                "lng": 110.3775 + math.cos(elapsed / 20.0) * 0.0002,
                "relative_alt_m": 25.0,
                "absolute_alt_m": None,
                "gps_status": 3,
                "gps_hdop": 0.9,
                "satellites": 14,
            },
            "attitude": {
                "roll_deg": math.sin(elapsed) * 5.0,
                "pitch_deg": math.cos(elapsed) * 3.0,
                "yaw_deg": elapsed * 5.0 % 360.0,
                "heading_deg": elapsed * 5.0 % 360.0,
                "ground_course_deg": elapsed * 5.0 % 360.0,
            },
            "velocity": {
                "airspeed_m_s": 12.0,
                "groundspeed_m_s": 11.5,
                "vertical_speed_m_s": 0.0,
            },
            "battery": {
                "remaining_percent": 78.0,
                "voltage_v": 22.4,
                "current_a": 4.2,
            },
            "ekf": {
                "ok": True,
                "velocity_variance": 0.1,
                "pos_variance": 0.2,
                "compass_variance": 0.1,
            },
            "vibration": {
                "x": 0.5,
                "y": 0.4,
                "z": 1.2,
            },
            "status": {
                "dist_to_home_m": elapsed * 10,
                "time_in_air_s": elapsed,
                "time_since_boot_s": elapsed + 600,
            },
        }


class FakeBridgeHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/api/v1/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "timestamp": time.time(),
                    "service": "mission-planner-bridge",
                    "version": "fake-1.5.0",
                    "capabilities": ["telemetry", "mission", "messages", "arm", "disarm", "set-flight-mode", "set-current-waypoint", "reboot"],
                    "vehicle_connected": True,
                    "snapshot_timestamp": time.time(),
                },
            )
            return
        if self.path == "/api/v1/telemetry":
            self._send_json(200, FakeBridgeState.telemetry())
            return
        if self.path == "/api/v1/mission":
            self._send_json(
                200,
                {
                    "ok": True,
                    "timestamp": time.time(),
                    "source": "fake-mission-planner",
                    "count": len(FakeBridgeState.mission),
                    "current_seq": FakeBridgeState.current_seq(),
                    "waypoints": FakeBridgeState.mission,
                },
            )
            return
        if self.path == "/api/v1/messages":
            now = time.time()
            self._send_json(
                200,
                {
                    "ok": True,
                    "timestamp": now,
                    "source": "fake-mission-planner",
                    "count": len(FakeBridgeState.messages),
                    "messages": [
                        {
                            "timestamp": now - index * 4,
                            "message": message,
                            "source": "fake.messages",
                        }
                        for index, message in enumerate(FakeBridgeState.messages)
                    ],
                    "sources_checked": ["fake.messages"],
                },
            )
            return
        self._send_json(404, {"ok": False, "error": "Route not found"})

    def do_POST(self):
        if self.path == "/api/v1/commands/reboot":
            payload = self._read_json()
            if FakeBridgeState.armed:
                self._send_json(400, {"ok": False, "error": "Reboot is only allowed while vehicle is disarmed"})
                return
            FakeBridgeState.reboot_count += 1
            self._send_json(
                202,
                {
                    "ok": True,
                    "accepted": True,
                    "request_id": payload.get("request_id"),
                    "command": "reboot",
                    "message": "Flight controller reboot started; waiting for Mission Planner to reconnect",
                    "timestamp": time.time(),
                },
            )
            return
        if self.path in {"/api/v1/commands/arm", "/api/v1/commands/disarm"}:
            payload = self._read_json()
            FakeBridgeState.armed = self.path.endswith("/arm")
            command = "arm" if FakeBridgeState.armed else "disarm"
            self._send_json(
                200,
                {
                    "ok": True,
                    "request_id": payload.get("request_id"),
                    "command": command,
                    "message": f"{command.capitalize()} request sent",
                    "timestamp": time.time(),
                },
            )
            return
        if self.path == "/api/v1/commands/set-flight-mode":
            payload = self._read_json()
            mode = str(payload.get("mode", "")).upper().replace("_", "")
            if mode not in {"MANUAL", "FBWA", "AUTO", "RTL", "QSTABILIZE", "QHOVER", "QLAND"}:
                self._send_json(400, {"ok": False, "error": f"Unsupported flight mode: {mode}"})
                return
            FakeBridgeState.flight_mode = mode
            self._send_json(
                200,
                {
                    "ok": True,
                    "request_id": payload.get("request_id"),
                    "command": "set-flight-mode",
                    "message": f"Flight mode change requested: {mode}",
                    "timestamp": time.time(),
                },
            )
            return
        if self.path == "/api/v1/commands/set-current-waypoint":
            payload = self._read_json()
            try:
                seq = int(payload.get("seq"))
            except (TypeError, ValueError):
                self._send_json(400, {"ok": False, "error": "seq is required and must be an integer"})
                return
            if seq < 0 or seq >= len(FakeBridgeState.mission):
                self._send_json(400, {"ok": False, "error": f"Waypoint index {seq} is outside mission range 0..{len(FakeBridgeState.mission) - 1}"})
                return
            FakeBridgeState.current_waypoint_seq = seq
            self._send_json(
                200,
                {
                    "ok": True,
                    "request_id": payload.get("request_id"),
                    "command": "set-current-waypoint",
                    "seq": seq,
                    "message": f"Current mission waypoint requested: WP {seq}",
                    "timestamp": time.time(),
                },
            )
            return
        self._send_json(404, {"ok": False, "error": "Route not found"})

    def log_message(self, message, *args):
        print(f"[fake-bridge] {self.address_string()} {message % args}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()

    try:
        server = ThreadingHTTPServer((args.host, args.port), FakeBridgeHandler)
    except PermissionError as exc:
        raise SystemExit(
            f"Cannot bind http://{args.host}:{args.port}: {exc}\n"
            "The real Mission Planner bridge may already be using this port. "
            "Run the fake bridge with --port 5002."
        )
    print(f"Fake Mission Planner bridge listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
