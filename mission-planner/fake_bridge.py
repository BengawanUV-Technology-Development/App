"""Development-only fake for the Mission Planner bridge contract."""

import argparse
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeBridgeState:
    started_at = time.time()
    flight_mode = "QHOVER"

    @classmethod
    def telemetry(cls):
        elapsed = time.time() - cls.started_at
        return {
            "ok": True,
            "timestamp": time.time(),
            "source": "fake-mission-planner",
            "vehicle": {
                "connected": True,
                "armed": False,
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
                    "vehicle_connected": True,
                    "snapshot_timestamp": time.time(),
                },
            )
            return
        if self.path == "/api/v1/telemetry":
            self._send_json(200, FakeBridgeState.telemetry())
            return
        self._send_json(404, {"ok": False, "error": "Route not found"})

    def do_POST(self):
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
        self._send_json(404, {"ok": False, "error": "Route not found"})

    def log_message(self, message, *args):
        print(f"[fake-bridge] {self.address_string()} {message % args}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), FakeBridgeHandler)
    print(f"Fake Mission Planner bridge listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

