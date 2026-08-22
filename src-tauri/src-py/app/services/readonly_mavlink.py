"""Receive-only MAVLink telemetry from the local router.

This service is intentionally implemented on a raw UDP socket instead of a
MAVSDK ``System``.  It binds to the router's web telemetry port and only calls
``recvfrom``.  There is no serial device, MAVSDK action plugin, or socket send
operation in this process, so the web backend cannot issue a vehicle command.
"""
from __future__ import annotations

import logging
import math
import socket
import threading
from time import time
from typing import Any

from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega as mavlink

from app.config import (
    MAVLINK_HEARTBEAT_TIMEOUT_SECONDS,
    TELEMETRY_LOG_INTERVAL_SECONDS,
)
from app.utils.session_log import SessionLogStore
from app.utils.state import StateManager


logger = logging.getLogger(__name__)


_SEVERITY_NAMES = {
    0: "EMERGENCY",
    1: "ALERT",
    2: "CRITICAL",
    3: "ERROR",
    4: "WARNING",
    5: "NOTICE",
    6: "INFO",
    7: "DEBUG",
}


class ReadonlyMavlinkReceiver:
    """Small receive-only MAVLink v1/v2 UDP receiver."""

    def __init__(
        self,
        state_manager: StateManager,
        session_log_store: SessionLogStore | None,
        host: str,
        port: int,
        heartbeat_timeout: float = MAVLINK_HEARTBEAT_TIMEOUT_SECONDS,
        telemetry_log_interval: float = TELEMETRY_LOG_INTERVAL_SECONDS,
    ) -> None:
        self.state_manager = state_manager
        self.session_log_store = session_log_store
        self.host = host
        self.port = port
        self.heartbeat_timeout = heartbeat_timeout
        self.telemetry_log_interval = telemetry_log_interval

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._last_heartbeat: float | None = None
        self._last_log: float = 0.0

    @property
    def system_address(self) -> str:
        return f"udpin://{self.host}:{self.port}"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="mavlink-readonly-receiver",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        current_socket = self._socket
        if current_socket is not None:
            current_socket.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None
        self._socket = None

    def _run(self) -> None:
        self.state_manager.update(
            connected=False,
            status="CONNECTING",
            error=None,
            source="mavlink-udp-readonly",
            system_address=self.system_address,
        )

        while not self._stop_event.is_set():
            current_socket: socket.socket | None = None
            try:
                current_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # Do not enable SO_REUSEPORT/SO_REUSEADDR: two readers on the
                # telemetry port would make packet delivery nondeterministic.
                current_socket.bind((self.host, self.port))
                current_socket.settimeout(1.0)
                self._socket = current_socket
                self._last_heartbeat = None
                self.state_manager.update(
                    connected=False,
                    status="CONNECTING",
                    error=None,
                    system_address=self.system_address,
                )
                logger.info("MAVLink receive-only UDP listening on %s", self.system_address)

                parser = mavlink.MAVLink(None)
                parser.robust_parsing = True

                while not self._stop_event.is_set():
                    try:
                        packet, _sender = current_socket.recvfrom(65535)
                    except socket.timeout:
                        self._refresh_connection_state()
                        continue

                    # The only socket operation in this service is recvfrom.
                    # Parsing a packet cannot generate a response to its sender.
                    for message in parser.parse_buffer(packet) or []:
                        self._handle_message(message)

                    self._refresh_connection_state()
                    self._record_telemetry_if_due()

            except OSError as exc:
                if not self._stop_event.is_set():
                    message = f"UDP telemetry listener error on {self.system_address}: {exc}"
                    logger.error(message)
                    self.state_manager.update(connected=False, status="OFFLINE", error=message)
                    self._stop_event.wait(2.0)
            except Exception as exc:  # Keep the backend alive on parser errors.
                logger.exception("Unexpected read-only MAVLink receiver error")
                self.state_manager.update(connected=False, status="OFFLINE", error=str(exc))
                self._stop_event.wait(2.0)
            finally:
                if current_socket is not None:
                    current_socket.close()
                if self._socket is current_socket:
                    self._socket = None

    def _refresh_connection_state(self) -> None:
        if self._last_heartbeat is None:
            return

        age = time() - self._last_heartbeat
        if age <= self.heartbeat_timeout:
            self.state_manager.update(connected=True, status="ACTIVE", error=None)
        else:
            self.state_manager.update(
                connected=False,
                status="OFFLINE",
                error=f"No MAVLink heartbeat received for {age:.1f}s",
            )

    def _handle_message(self, message: Any) -> None:
        now = time()
        message_type = message.get_type()
        self.state_manager.update(last_update=now)

        if message_type == "HEARTBEAT":
            self._last_heartbeat = now
            mode = None
            try:
                mode = mavutil.mode_string_v10(message)
            except Exception:
                mode = str(getattr(message, "custom_mode", "UNKNOWN"))

            self.state_manager.update(
                connected=True,
                status="ACTIVE",
                error=None,
                armed=bool(getattr(message, "base_mode", 0) & mavlink.MAV_MODE_FLAG_SAFETY_ARMED),
                flight_mode=mode,
            )
            return

        if message_type == "GLOBAL_POSITION_INT":
            self.state_manager.update(
                lat=self._scaled(getattr(message, "lat", None), 1e7),
                lng=self._scaled(getattr(message, "lon", None), 1e7),
                alt_amsl=self._scaled(getattr(message, "alt", None), 1000.0),
                alt=self._scaled(getattr(message, "relative_alt", None), 1000.0),
            )
            return

        if message_type == "ATTITUDE":
            self.state_manager.update(
                roll_deg=round(math.degrees(float(message.roll)), 2),
                pitch_deg=round(math.degrees(float(message.pitch)), 2),
                yaw_deg=round(math.degrees(float(message.yaw)), 2),
            )
            return

        if message_type == "VFR_HUD":
            # VFR_HUD.alt is MSL. Keep the alt field reserved for the
            # GLOBAL_POSITION_INT.relative_alt value so the webapp matches
            # QGroundControl's default relative-to-home altitude display.
            self.state_manager.update(
                airspeed_m_s=float(message.airspeed),
                groundspeed_m_s=float(message.groundspeed),
                heading_deg=float(message.heading),
                v_speed_m_s=float(message.climb),
            )
            return

        if message_type in {"SYS_STATUS", "BATTERY_STATUS"}:
            battery_remaining = getattr(message, "battery_remaining", None)
            if battery_remaining is not None and int(battery_remaining) >= 0:
                self.state_manager.update(battery_percent=float(battery_remaining))
            if message_type == "SYS_STATUS":
                self._update_prearm_health(message)
            return

        if message_type == "EKF_STATUS_REPORT":
            self.state_manager.update(
                ekf_velocity=float(getattr(message, "velocity_variance", 0.0)),
                ekf_pos_horiz=float(getattr(message, "pos_horiz_variance", 0.0)),
                ekf_pos_vert=float(getattr(message, "pos_vert_variance", 0.0)),
                ekf_compass=float(getattr(message, "compass_variance", 0.0)),
                ekf_terrain=float(getattr(message, "terrain_alt_variance", 0.0)),
            )
            return

        if message_type == "VIBRATION":
            self.state_manager.update(
                vibration_x=float(message.vibration_x),
                vibration_y=float(message.vibration_y),
                vibration_z=float(message.vibration_z),
                vibration_clip0=int(message.clipping_0),
                vibration_clip1=int(message.clipping_1),
                vibration_clip2=int(message.clipping_2),
            )
            return

        if message_type == "STATUSTEXT":
            text = self._decode_text(getattr(message, "text", ""))
            message_type_name = _SEVERITY_NAMES.get(int(getattr(message, "severity", 6)), "INFO")
            formatted = f"[{message_type_name}] {text}"
            self.state_manager.update(
                status_text=formatted,
                status_text_type=message_type_name,
            )
            self.state_manager.append_status_text(text, message_type_name)
            if self.session_log_store:
                self.session_log_store.record_event(
                    "status_text",
                    message=formatted,
                    severity=message_type_name,
                )

    def _update_prearm_health(self, message: Any) -> None:
        health = int(getattr(message, "onboard_control_sensors_health", 0))
        position_health = health & (
            mavlink.MAV_SYS_STATUS_SENSOR_GPS
            | mavlink.MAV_SYS_STATUS_SENSOR_VISION_POSITION
        )
        self.state_manager.update_prearm_health(
            is_gyrometer_calibration_ok=bool(health & mavlink.MAV_SYS_STATUS_SENSOR_3D_GYRO),
            is_accelerometer_calibration_ok=bool(health & mavlink.MAV_SYS_STATUS_SENSOR_3D_ACCEL),
            is_magnetometer_calibration_ok=bool(health & mavlink.MAV_SYS_STATUS_SENSOR_3D_MAG),
            is_local_position_ok=bool(position_health),
            is_global_position_ok=bool(health & mavlink.MAV_SYS_STATUS_SENSOR_GPS),
            is_home_position_ok=bool(health & mavlink.MAV_SYS_STATUS_SENSOR_GPS),
            is_armable=bool(health & mavlink.MAV_SYS_STATUS_PREARM_CHECK),
        )

    def _record_telemetry_if_due(self) -> None:
        if not self.session_log_store:
            return
        now = time()
        if now - self._last_log >= self.telemetry_log_interval:
            self.session_log_store.record_telemetry(self.state_manager.get())
            self._last_log = now

    @staticmethod
    def _scaled(value: Any, divisor: float) -> float | None:
        if value is None:
            return None
        return float(value) / divisor

    @staticmethod
    def _decode_text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        return str(value).rstrip("\x00")
