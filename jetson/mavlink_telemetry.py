#!/usr/bin/env python3
"""Read-only MAVLink telemetry for the Jetson flight recorder.

The recorder connects to the local MAVLink Router TCP server instead of
opening the flight-controller serial device itself.  The intended path is:

    flight controller -> /dev/ttyACM0 -> mavlink-router -> TCP 127.0.0.1:5760
                                                     -> this collector

This module deliberately has no command-sending code.  It uses only the
Python standard library so a capture-only flight can work on a minimal
Jetson image.  MAVLink frames are parsed for the common telemetry messages
needed by the recorder; unknown messages are ignored but still counted.
"""

from __future__ import annotations

import math
import os
import socket
import struct
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _unpack(payload: bytes, fmt: str, offset: int) -> Any | None:
    size = struct.calcsize("<" + fmt)
    if offset < 0 or len(payload) < offset + size:
        return None
    return struct.unpack_from("<" + fmt, payload, offset)[0]


def _finite_or_none(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    try:
        return value if math.isfinite(float(value)) else None
    except (TypeError, ValueError):
        return None


def _heading_from_yaw(yaw_rad: float | None) -> float | None:
    if yaw_rad is None:
        return None
    value = math.degrees(yaw_rad) % 360.0
    return round(value, 6)


def _mode_name(vehicle_type: int | None, custom_mode: int | None) -> str | None:
    if custom_mode is None:
        return None

    # ArduCopter custom modes.
    copter_modes = {
        0: "STABILIZE",
        1: "ACRO",
        2: "ALT_HOLD",
        3: "AUTO",
        4: "GUIDED",
        5: "LOITER",
        6: "RTL",
        7: "CIRCLE",
        9: "LAND",
        11: "DRIFT",
        13: "SPORT",
        14: "FLIP",
        15: "AUTOTUNE",
        16: "POSHOLD",
        17: "BRAKE",
        18: "THROW",
        19: "AVOID_ADSB",
        20: "GUIDED_NOGPS",
        21: "SMART_RTL",
        22: "FLOWHOLD",
        23: "FOLLOW",
        24: "ZIGZAG",
        25: "SYSTEMID",
        26: "AUTOROTATE",
        27: "AUTO_RTL",
    }
    # ArduPlane custom modes.
    plane_modes = {
        0: "MANUAL",
        1: "CIRCLE",
        2: "STABILIZE",
        3: "TRAINING",
        4: "ACRO",
        5: "FBWA",
        6: "FBWB",
        7: "CRUISE",
        8: "AUTOTUNE",
        10: "AUTO",
        11: "RTL",
        12: "LOITER",
        13: "TAKEOFF",
        14: "AVOID_ADSB",
        15: "GUIDED",
        16: "INITIALISING",
        17: "QSTABILIZE",
        18: "QHOVER",
        19: "QLOITER",
        20: "QLAND",
        21: "QRTL",
        22: "QAUTOTUNE",
        23: "QACRO",
        24: "THERMAL",
        25: "LOITER_ALT_QLAND",
    }
    if vehicle_type == 1:  # MAV_TYPE_FIXED_WING
        modes = plane_modes
    elif vehicle_type in {2, 3, 4, 13, 14, 15, 19, 20, 21, 22, 23}:
        modes = copter_modes
    else:
        modes = copter_modes
    return modes.get(int(custom_mode), f"CUSTOM_{int(custom_mode)}")


@dataclass(frozen=True)
class MAVLinkMessage:
    system_id: int
    component_id: int
    message_id: int
    payload: bytes


class MAVLinkStreamParser:
    """Extract MAVLink 1 and MAVLink 2 messages from arbitrary TCP chunks.

    Checksum validation is intentionally omitted here.  The MAVLink Router
    has already read a local serial/UDP stream and the recorder needs a
    best-effort read-only sidecar; a malformed message is harmless because
    all field reads below are length-checked.
    """

    MAVLINK_V1_MAGIC = 0xFE
    MAVLINK_V2_MAGIC = 0xFD

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[MAVLinkMessage]:
        if data:
            self._buffer.extend(data)

        messages: list[MAVLinkMessage] = []
        while True:
            magic_index = next(
                (
                    index
                    for index, value in enumerate(self._buffer)
                    if value in {self.MAVLINK_V1_MAGIC, self.MAVLINK_V2_MAGIC}
                ),
                None,
            )
            if magic_index is None:
                self._buffer.clear()
                break
            if magic_index:
                del self._buffer[:magic_index]

            magic = self._buffer[0]
            if magic == self.MAVLINK_V1_MAGIC:
                header_size = 6
                if len(self._buffer) < header_size:
                    break
                payload_length = self._buffer[1]
                frame_length = header_size + payload_length + 2
                if len(self._buffer) < frame_length:
                    break
                frame = bytes(self._buffer[:frame_length])
                del self._buffer[:frame_length]
                messages.append(
                    MAVLinkMessage(
                        system_id=frame[3],
                        component_id=frame[4],
                        message_id=frame[5],
                        payload=frame[6 : 6 + payload_length],
                    )
                )
                continue

            header_size = 10
            if len(self._buffer) < header_size:
                break
            payload_length = self._buffer[1]
            has_signature = bool(self._buffer[2] & 0x01)
            frame_length = header_size + payload_length + 2 + (13 if has_signature else 0)
            if len(self._buffer) < frame_length:
                break
            frame = bytes(self._buffer[:frame_length])
            del self._buffer[:frame_length]
            messages.append(
                MAVLinkMessage(
                    system_id=frame[5],
                    component_id=frame[6],
                    message_id=int.from_bytes(frame[7:10], "little"),
                    payload=frame[10 : 10 + payload_length],
                )
            )
        return messages


def _empty_telemetry() -> dict[str, Any]:
    return {
        "connected": False,
        "status": "SOURCE_OFFLINE",
        "source": "mavlink-router-tcp",
        "lat": None,
        "lng": None,
        "alt": None,
        "alt_amsl": None,
        "armed": None,
        "flight_mode": None,
        "custom_mode": None,
        "vehicle_type": None,
        "autopilot": None,
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
        "gps_vdop": None,
        "satellites": None,
        "dist_to_home_m": None,
        "time_in_air_s": None,
        "time_since_boot_s": None,
        "ekf_ok": None,
        "landed_state": None,
        "home_lat": None,
        "home_lng": None,
        "home_alt_amsl": None,
        "system_id": None,
        "component_id": None,
        "time_boot_ms": None,
        "source_timestamp_unix": None,
        "received_at_unix": None,
        "mavlink_message_count": 0,
        "last_message_id": None,
    }


class MAVLinkTelemetryCollector:
    """Maintain the newest read-only MAVLink state for frame alignment."""

    def __init__(self):
        self.host = os.getenv("JETSON_MAVLINK_TCP_HOST", "127.0.0.1").strip()
        if not self.host:
            raise ValueError("JETSON_MAVLINK_TCP_HOST must not be empty")
        self.port = _env_int("JETSON_MAVLINK_TCP_PORT", 5760, 1, 65535)
        self.connect_timeout = _env_float("JETSON_MAVLINK_CONNECT_TIMEOUT_SECONDS", 1.0, 0.1, 30.0)
        self.reconnect_delay = _env_float("JETSON_MAVLINK_RECONNECT_SECONDS", 2.0, 0.2, 60.0)
        self.stale_after = _env_float("JETSON_MAVLINK_STALE_AFTER_SECONDS", 2.0, 0.1, 60.0)

        self.source = f"mavlink-router-tcp://{self.host}:{self.port}"
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._parser = MAVLinkStreamParser()
        self._state = _empty_telemetry()
        self._state["source"] = self.source
        self._last_received_at: float | None = None
        self._source_connected = False
        self._source_error: str | None = None
        self._bytes_received = 0
        self._connection_count = 0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="jetson-mavlink-telemetry",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            current = self._socket
            self._socket = None
        if current is not None:
            try:
                current.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                current.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=3)
        with self._lock:
            self._source_connected = False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            connection: socket.socket | None = None
            try:
                connection = socket.create_connection(
                    (self.host, self.port),
                    timeout=self.connect_timeout,
                )
                connection.settimeout(1.0)
                with self._lock:
                    self._socket = connection
                    self._source_connected = True
                    self._source_error = None
                    self._connection_count += 1
                while not self._stop_event.is_set():
                    try:
                        data = connection.recv(8192)
                    except socket.timeout:
                        continue
                    if not data:
                        raise OSError("MAVLink router TCP connection closed")
                    with self._lock:
                        self._bytes_received += len(data)
                    for message in self._parser.feed(data):
                        self._handle_message(message)
            except (OSError, ValueError) as exc:
                with self._lock:
                    self._source_connected = False
                    self._source_error = str(exc)
            finally:
                with self._lock:
                    if self._socket is connection:
                        self._socket = None
                    self._source_connected = False
                if connection is not None:
                    try:
                        connection.close()
                    except OSError:
                        pass
            self._stop_event.wait(self.reconnect_delay)

    def _handle_message(self, message: MAVLinkMessage) -> None:
        now = time.time()
        payload = message.payload
        with self._lock:
            state = self._state
            state["system_id"] = message.system_id
            state["component_id"] = message.component_id
            state["received_at_unix"] = now
            state["mavlink_message_count"] += 1
            state["last_message_id"] = message.message_id
            self._last_received_at = now

            if message.message_id == 0:  # HEARTBEAT
                custom_mode = _unpack(payload, "I", 0)
                vehicle_type = _unpack(payload, "B", 4)
                autopilot = _unpack(payload, "B", 5)
                base_mode = _unpack(payload, "B", 6)
                state["custom_mode"] = custom_mode
                state["vehicle_type"] = vehicle_type
                state["autopilot"] = autopilot
                state["armed"] = bool(base_mode & 0x80) if base_mode is not None else None
                state["flight_mode"] = _mode_name(vehicle_type, custom_mode)
            elif message.message_id == 1:  # SYS_STATUS
                voltage_mv = _unpack(payload, "H", 14)
                current_ca = _unpack(payload, "h", 16)
                remaining = _unpack(payload, "b", 18)
                if voltage_mv not in (None, 0, 65535):
                    state["battery_voltage_v"] = voltage_mv / 1000.0
                if current_ca not in (None, -1):
                    state["battery_current_a"] = current_ca / 100.0
                if remaining not in (None, -1):
                    state["battery_percent"] = remaining
            elif message.message_id == 2:  # SYSTEM_TIME
                time_boot_ms = _unpack(payload, "Q", 8)
                if time_boot_ms is not None:
                    state["time_boot_ms"] = time_boot_ms
            elif message.message_id == 24:  # GPS_RAW_INT
                time_usec = _unpack(payload, "Q", 0)
                fix_type = _unpack(payload, "B", 8)
                lat = _unpack(payload, "i", 9)
                lng = _unpack(payload, "i", 13)
                alt_mm = _unpack(payload, "i", 17)
                eph_cm = _unpack(payload, "H", 21)
                epv_cm = _unpack(payload, "H", 23)
                satellites = _unpack(payload, "B", 29)
                state["gps_status"] = fix_type
                if lat not in (None, 0) and lng not in (None, 0):
                    state["lat"] = lat / 10_000_000.0
                    state["lng"] = lng / 10_000_000.0
                if alt_mm is not None:
                    state["alt_amsl"] = alt_mm / 1000.0
                state["gps_hdop"] = None if eph_cm in (None, 65535) else eph_cm / 100.0
                state["gps_vdop"] = None if epv_cm in (None, 65535) else epv_cm / 100.0
                state["satellites"] = None if satellites in (None, 255) else satellites
                # MAVLink permits GPS_RAW_INT.time_usec to be either UNIX
                # epoch time or time since boot. Only label it as UNIX when
                # its magnitude makes that unambiguous.
                state["source_timestamp_unix"] = (
                    time_usec / 1_000_000.0
                    if time_usec and time_usec >= 1_000_000_000_000
                    else None
                )
            elif message.message_id == 30:  # ATTITUDE
                time_boot_ms = _unpack(payload, "I", 0)
                roll = _unpack(payload, "f", 4)
                pitch = _unpack(payload, "f", 8)
                yaw = _unpack(payload, "f", 12)
                state["time_boot_ms"] = time_boot_ms
                state["roll_deg"] = None if roll is None else math.degrees(roll)
                state["pitch_deg"] = None if pitch is None else math.degrees(pitch)
                state["yaw_deg"] = _heading_from_yaw(yaw)
            elif message.message_id == 33:  # GLOBAL_POSITION_INT
                time_boot_ms = _unpack(payload, "I", 0)
                lat = _unpack(payload, "i", 4)
                lng = _unpack(payload, "i", 8)
                alt_mm = _unpack(payload, "i", 12)
                relative_alt_mm = _unpack(payload, "i", 16)
                vx_cms = _unpack(payload, "h", 20)
                vy_cms = _unpack(payload, "h", 22)
                vz_cms = _unpack(payload, "h", 24)
                heading_cdeg = _unpack(payload, "H", 26)
                state["time_boot_ms"] = time_boot_ms
                if lat not in (None, 0) and lng not in (None, 0):
                    state["lat"] = lat / 10_000_000.0
                    state["lng"] = lng / 10_000_000.0
                if alt_mm is not None:
                    state["alt_amsl"] = alt_mm / 1000.0
                if relative_alt_mm is not None:
                    state["alt"] = relative_alt_mm / 1000.0
                if vx_cms is not None and vy_cms is not None:
                    state["groundspeed_m_s"] = math.hypot(vx_cms, vy_cms) / 100.0
                if vz_cms is not None:
                    state["v_speed_m_s"] = -vz_cms / 100.0
                state["heading_deg"] = (
                    None if heading_cdeg in (None, 65535) else heading_cdeg / 100.0
                )
            elif message.message_id == 74:  # VFR_HUD
                airspeed = _unpack(payload, "f", 0)
                groundspeed = _unpack(payload, "f", 4)
                heading = _unpack(payload, "h", 8)
                alt = _unpack(payload, "f", 12)
                climb = _unpack(payload, "f", 16)
                state["airspeed_m_s"] = _finite_or_none(airspeed)
                state["groundspeed_m_s"] = _finite_or_none(groundspeed)
                state["heading_deg"] = None if heading is None or heading < 0 else float(heading % 360)
                if state["alt"] is None:
                    state["alt"] = _finite_or_none(alt)
                state["v_speed_m_s"] = _finite_or_none(climb)
            elif message.message_id == 124:  # GPS2_RAW
                fix_type = _unpack(payload, "B", 8)
                satellites = _unpack(payload, "B", 29)
                if state["gps_status"] is None or (fix_type or 0) > (state["gps_status"] or 0):
                    state["gps_status"] = fix_type
                    state["satellites"] = None if satellites in (None, 255) else satellites
            elif message.message_id == 147:  # BATTERY_STATUS
                voltages = [
                    _unpack(payload, "H", 4 + index * 2)
                    for index in range(10)
                ]
                voltage_mv = next((value for value in voltages if value not in (None, 0, 65535)), None)
                current_ca = _unpack(payload, "h", 24)
                remaining = _unpack(payload, "b", 30)
                if state["battery_voltage_v"] is None and voltage_mv is not None:
                    state["battery_voltage_v"] = voltage_mv / 1000.0
                if current_ca not in (None, -1) and state["battery_current_a"] is None:
                    state["battery_current_a"] = current_ca / 100.0
                if remaining not in (None, -1) and state["battery_percent"] is None:
                    state["battery_percent"] = remaining
            elif message.message_id == 242:  # HOME_POSITION
                lat = _unpack(payload, "i", 0)
                lng = _unpack(payload, "i", 4)
                alt_mm = _unpack(payload, "i", 8)
                if lat not in (None, 0) and lng not in (None, 0):
                    state["home_lat"] = lat / 10_000_000.0
                    state["home_lng"] = lng / 10_000_000.0
                if alt_mm is not None:
                    state["home_alt_amsl"] = alt_mm / 1000.0
            elif message.message_id == 245:  # EXTENDED_SYS_STATE
                landed_state = _unpack(payload, "B", 1)
                state["landed_state"] = landed_state

    def _status_locked(self, now: float) -> tuple[str, float | None]:
        if self._last_received_at is None:
            return ("NO_DATA" if self._source_connected else "SOURCE_OFFLINE", None)
        age = max(0.0, now - self._last_received_at)
        if age > self.stale_after:
            return "STALE", age
        return "ACTIVE", age

    def snapshot(self, captured_at: float | None = None) -> dict[str, Any]:
        now = captured_at if captured_at is not None else time.time()
        with self._lock:
            status, age = self._status_locked(now)
            telemetry = deepcopy(self._state)
            telemetry["status"] = status
            telemetry["connected"] = status == "ACTIVE"
            telemetry["source"] = self.source
            telemetry["received_at_unix"] = self._last_received_at
            telemetry["telemetry_age_ms"] = None if age is None else round(age * 1000.0, 3)
            return {
                "schema_version": "1.0",
                "source": self.source,
                "status": status,
                "connected": status == "ACTIVE",
                "received_at_unix": self._last_received_at,
                "age_ms": None if age is None else round(age * 1000.0, 3),
                "source_error": self._source_error,
                "bytes_received": self._bytes_received,
                "connection_count": self._connection_count,
                "telemetry": telemetry,
            }

    def metadata(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "source": self.source,
            "transport": "MAVLink over TCP from local mavlink-router",
            "host": self.host,
            "port": self.port,
            "read_only": True,
            "status": snapshot["status"],
            "connected": snapshot["connected"],
            "received_at_unix": snapshot["received_at_unix"],
            "source_error": snapshot["source_error"],
            "bytes_received": snapshot["bytes_received"],
            "connection_count": snapshot["connection_count"],
        }
