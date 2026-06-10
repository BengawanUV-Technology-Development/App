import json
import os
import threading
import time
from copy import deepcopy
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class MissionPlannerBridgeError(RuntimeError):
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.payload = payload
        super().__init__(payload.get("error") or f"Mission Planner bridge HTTP {status_code}")


class MissionPlannerAdapter:
    def __init__(
        self,
        base_url: str | None = None,
        poll_interval_seconds: float = 0.2,
        stale_after_seconds: float = 2.0,
        request_timeout_seconds: float = 1.0,
    ):
        self.base_url = (base_url or os.getenv("MISSION_PLANNER_API_URL", "http://127.0.0.1:5000")).rstrip("/")
        self.poll_interval_seconds = poll_interval_seconds
        self.stale_after_seconds = stale_after_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._lock = threading.Lock()
        self._version = 0
        self._last_poll_at = None
        self._last_success_at = None
        self._bridge_error = None
        self._raw = None
        self._telemetry = self._empty_telemetry()
        self._thread = None

    @staticmethod
    def _empty_telemetry():
        return {
            "connected": False,
            "status": "BRIDGE_OFFLINE",
            "state_valid": False,
            "lat": None,
            "lng": None,
            "alt": None,
            "alt_amsl": None,
            "armed": None,
            "flight_mode": None,
            "battery_percent": None,
            "battery_voltage_v": None,
            "battery_current_a": None,
            "roll_deg": None,
            "pitch_deg": None,
            "yaw_deg": None,
            "heading_deg": None,
            "airspeed_m_s": None,
            "groundspeed_m_s": None,
            "v_speed_m_s": None,
            "gps_status": None,
            "gps_hdop": None,
            "satellites": None,
            "last_update": None,
            "error": None,
            "source": "mission-planner",
        }

    def _request_json(self, path: str, method: str = "GET", payload: dict | None = None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(self.base_url + path, data=body, method=method)
        request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=self.request_timeout_seconds) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(response_body)
            except json.JSONDecodeError:
                payload = {"ok": False, "error": response_body or f"Mission Planner bridge HTTP {exc.code}"}
            raise MissionPlannerBridgeError(exc.code, payload) from exc
        except URLError as exc:
            raise RuntimeError(f"Mission Planner bridge unavailable: {exc.reason}") from exc

    @staticmethod
    def _normalize(raw: dict):
        vehicle = raw.get("vehicle") or {}
        position = raw.get("position") or {}
        attitude = raw.get("attitude") or {}
        velocity = raw.get("velocity") or {}
        battery = raw.get("battery") or {}
        bridge_vehicle_connected = bool(vehicle.get("connected"))
        flight_mode = vehicle.get("flight_mode")
        mode_valid = str(flight_mode or "").strip().upper() not in {"", "UNKNOWN", "NONE"}
        state_valid = (
            mode_valid
            or int(position.get("gps_status") or 0) >= 3
            or float(battery.get("voltage_v") or 0) > 0
        )
        connected = bridge_vehicle_connected and state_valid

        return {
            "connected": connected,
            "status": "ACTIVE" if connected else "VEHICLE_STATE_UNAVAILABLE" if bridge_vehicle_connected else "VEHICLE_DISCONNECTED",
            "state_valid": state_valid,
            "lat": position.get("lat"),
            "lng": position.get("lng"),
            "alt": position.get("relative_alt_m"),
            "alt_amsl": position.get("absolute_alt_m"),
            "armed": vehicle.get("armed"),
            "flight_mode": flight_mode,
            "battery_percent": battery.get("remaining_percent"),
            "battery_voltage_v": battery.get("voltage_v"),
            "battery_current_a": battery.get("current_a"),
            "roll_deg": attitude.get("roll_deg"),
            "pitch_deg": attitude.get("pitch_deg"),
            "yaw_deg": attitude.get("yaw_deg"),
            "heading_deg": attitude.get("heading_deg"),
            "airspeed_m_s": velocity.get("airspeed_m_s"),
            "groundspeed_m_s": velocity.get("groundspeed_m_s"),
            "v_speed_m_s": velocity.get("vertical_speed_m_s"),
            "gps_status": position.get("gps_status"),
            "gps_hdop": position.get("gps_hdop"),
            "satellites": position.get("satellites"),
            "last_update": raw.get("timestamp"),
            "error": None,
            "source": raw.get("source", "mission-planner"),
        }

    @staticmethod
    def _normalize_mission(raw: dict):
        waypoints = []
        for item in raw.get("waypoints") or []:
            lat = item.get("lat")
            lng = item.get("lng")
            try:
                lat = float(lat) if lat is not None else None
                lng = float(lng) if lng is not None else None
            except (TypeError, ValueError):
                lat = None
                lng = None

            try:
                alt_m = float(item.get("alt_m")) if item.get("alt_m") is not None else None
            except (TypeError, ValueError):
                alt_m = None

            waypoints.append({
                "index": item.get("index"),
                "seq": item.get("seq", item.get("index")),
                "command": item.get("command"),
                "command_name": item.get("command_name"),
                "frame": item.get("frame"),
                "lat": lat,
                "lng": lng,
                "alt_m": alt_m,
                "has_position": lat is not None and lng is not None and not (lat == 0.0 and lng == 0.0),
                "error": item.get("error"),
            })

        positioned = [item for item in waypoints if item["has_position"]]
        current_seq = raw.get("current_seq")
        try:
            current_seq = int(current_seq) if current_seq is not None else None
        except (TypeError, ValueError):
            current_seq = None
        current_waypoint = next(
            (item for item in waypoints if item.get("seq") == current_seq or item.get("index") == current_seq),
            None,
        )
        return {
            "ok": True,
            "timestamp": raw.get("timestamp", time.time()),
            "source": raw.get("source", "mission-planner"),
            "count": len(waypoints),
            "positioned_count": len(positioned),
            "current_seq": current_seq,
            "current_waypoint": current_waypoint,
            "waypoints": waypoints,
        }

    def poll_once(self):
        now = time.time()
        try:
            status, raw = self._request_json("/api/v1/telemetry")
            if status != 200 or not raw.get("ok"):
                raise RuntimeError("Mission Planner bridge returned an invalid telemetry response")
            telemetry = self._normalize(raw)
            with self._lock:
                self._last_poll_at = now
                self._last_success_at = now
                self._bridge_error = None
                self._raw = raw
                self._telemetry = telemetry
                self._version += 1
            return self.snapshot()
        except Exception as exc:
            with self._lock:
                self._last_poll_at = now
                self._bridge_error = str(exc)
                self._version += 1
            return self.snapshot()

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        def poll_loop():
            while True:
                started_at = time.time()
                self.poll_once()
                delay = max(0.0, self.poll_interval_seconds - (time.time() - started_at))
                time.sleep(delay)

        self._thread = threading.Thread(target=poll_loop, daemon=True, name="mission-planner-adapter")
        self._thread.start()

    def snapshot(self):
        with self._lock:
            now = time.time()
            telemetry = deepcopy(self._telemetry)
            last_success_at = self._last_success_at
            source_timestamp = telemetry.get("last_update")
            stale = (
                last_success_at is None
                or source_timestamp is None
                or now - float(source_timestamp) > self.stale_after_seconds
            )
            bridge_online = self._bridge_error is None and last_success_at is not None
            if stale:
                telemetry["status"] = "STALE" if bridge_online else "BRIDGE_OFFLINE"
                telemetry["error"] = self._bridge_error or "Mission Planner telemetry is stale"

            lat = telemetry.get("lat")
            lng = telemetry.get("lng")
            gps_status = telemetry.get("gps_status")
            gps_valid = (
                not stale
                and lat is not None
                and lng is not None
                and not (float(lat) == 0.0 and float(lng) == 0.0)
                and (gps_status is None or int(gps_status) >= 3)
            )
            return {
                "ok": True,
                "timestamp": now,
                "version": self._version,
                "stale": stale,
                "gps_valid": gps_valid,
                "bridge": {
                    "online": bridge_online,
                    "url": self.base_url,
                    "last_poll_at": self._last_poll_at,
                    "last_success_at": last_success_at,
                    "error": self._bridge_error,
                },
                "telemetry": telemetry,
            }

    def health(self):
        snapshot = self.snapshot()
        telemetry = snapshot["telemetry"]
        return {
            "ok": True,
            "timestamp": snapshot["timestamp"],
            "status": telemetry["status"],
            "connected": bool(telemetry["connected"]) and not snapshot["stale"],
            "stale": snapshot["stale"],
            "gps_valid": snapshot["gps_valid"],
            "last_update": telemetry["last_update"],
            "error": telemetry["error"],
            "source": "mission-planner-adapter",
            "bridge": snapshot["bridge"],
        }

    def send_command(self, command: str, payload: dict):
        status, response = self._request_json(f"/api/v1/commands/{command}", method="POST", payload=payload)
        return response, status

    def mission(self):
        status, raw = self._request_json("/api/v1/mission")
        if status != 200 or not raw.get("ok"):
            raise RuntimeError(raw.get("error") or "Mission Planner bridge returned an invalid mission response")
        return self._normalize_mission(raw)

    def messages(self):
        status, raw = self._request_json("/api/v1/messages")
        if status != 200 or not raw.get("ok"):
            raise RuntimeError(raw.get("error") or "Mission Planner bridge returned an invalid messages response")
        messages = []
        for item in raw.get("messages") or []:
            text = str(item.get("message") or "").strip()
            if not text:
                continue
            try:
                timestamp = float(item.get("timestamp")) if item.get("timestamp") is not None else None
            except (TypeError, ValueError):
                timestamp = None
            messages.append({
                "timestamp": timestamp,
                "message": text,
                "source": item.get("source") or raw.get("source", "mission-planner"),
            })
        messages.sort(
            key=lambda item: item.get("timestamp") if item.get("timestamp") is not None else 0,
            reverse=True,
        )
        return {
            "ok": True,
            "timestamp": raw.get("timestamp", time.time()),
            "source": raw.get("source", "mission-planner"),
            "count": len(messages),
            "messages": messages[:80],
            "sources_checked": raw.get("sources_checked") or [],
        }
