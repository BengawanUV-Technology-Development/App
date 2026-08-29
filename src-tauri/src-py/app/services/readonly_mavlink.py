"""Receive-only MAVLink telemetry from the local router."""

from __future__ import annotations

import logging
import math
import socket
import threading
from time import monotonic_ns, time_ns
from typing import Any, Callable

from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega as mavlink

from app.config import (
    TELEMETRY_DISCONNECTED_AFTER_SECONDS,
    TELEMETRY_RAW_DEBUG_ENABLED,
    TELEMETRY_STALE_AFTER_SECONDS,
)
from app.models import TelemetrySample
from app.services.mission_telemetry import MissionTelemetryRecorder
from app.services.time_normalizer import MavlinkTimeNormalizer
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
    """Small receive-only MAVLink v1/v2 UDP receiver.

    The receiver keeps the legacy latest-state projection for the web UI and
    emits one :class:`TelemetrySample` for each parsed MAVLink message. The
    latter retains per-message timing for mission evidence and later
    interpolation.
    """

    def __init__(
        self,
        state_manager: StateManager,
        session_log_store: SessionLogStore | None,
        host: str,
        port: int,
        heartbeat_timeout: float | None = None,
        telemetry_log_interval: float | None = None,
        stale_after: float = TELEMETRY_STALE_AFTER_SECONDS,
        disconnected_after: float = TELEMETRY_DISCONNECTED_AFTER_SECONDS,
        mission_recorder: MissionTelemetryRecorder | None = None,
        raw_debug_enabled: bool = TELEMETRY_RAW_DEBUG_ENABLED,
        telemetry_observer: Callable[[TelemetrySample], None] | None = None,
    ) -> None:
        self.state_manager = state_manager
        self.session_log_store = session_log_store
        self.host = host
        self.port = port

        # ``heartbeat_timeout`` was the old public constructor argument. Keep
        # it as a compatibility alias for stale timeout while the new health
        # contract is based on any valid parsed MAVLink update.
        self.stale_after = (
            float(heartbeat_timeout)
            if heartbeat_timeout is not None
            else float(stale_after)
        )
        self.disconnected_after = max(float(disconnected_after), self.stale_after)
        self.telemetry_log_interval = telemetry_log_interval
        self.mission_recorder = mission_recorder
        self.raw_debug_enabled = raw_debug_enabled
        self.telemetry_observer = telemetry_observer

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._last_heartbeat: float | None = None
        self._last_valid_receive_monotonic_ns: int | None = None
        self._socket_bound_monotonic_ns: int | None = None
        self._time_normalizer = MavlinkTimeNormalizer()

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
        self.state_manager.update(
            connected=False,
            status="DISCONNECTED",
        )

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
                self._last_valid_receive_monotonic_ns = None
                self._socket_bound_monotonic_ns = monotonic_ns()
                self._time_normalizer = MavlinkTimeNormalizer()
                self.state_manager.update(
                    connected=False,
                    status="CONNECTING",
                    error=None,
                    system_address=self.system_address,
                )
                logger.info(
                    "MAVLink receive-only UDP listening on %s",
                    self.system_address,
                )

                parser = mavlink.MAVLink(None)
                parser.robust_parsing = True

                while not self._stop_event.is_set():
                    try:
                        packet, _sender = current_socket.recvfrom(65535)
                    except socket.timeout:
                        self._refresh_connection_state()
                        continue

                    # Capture Ground receive time immediately after the
                    # blocking read returns, not before the next packet arrives.
                    receive_timestamp_ns = time_ns()
                    receive_monotonic_ns = monotonic_ns()

                    if self.raw_debug_enabled and self.mission_recorder:
                        self.mission_recorder.record_raw_packet(
                            packet,
                            receive_timestamp=receive_timestamp_ns,
                            receive_monotonic_ns=receive_monotonic_ns,
                        )

                    try:
                        messages = parser.parse_buffer(packet) or []
                    except Exception:
                        # A malformed packet must not terminate the receiver.
                        logger.exception("Ignoring malformed MAVLink UDP packet")
                        self._refresh_connection_state(receive_monotonic_ns)
                        continue

                    for message in messages:
                        try:
                            sample = self._handle_message(
                                message,
                                receive_timestamp_ns=receive_timestamp_ns,
                                receive_monotonic_ns=receive_monotonic_ns,
                            )
                        except Exception:
                            # Keep receiving later packets even if an optional
                            # field from one dialect/message is unexpected.
                            logger.exception("Ignoring malformed MAVLink message")
                            continue
                        if sample is not None and self.mission_recorder:
                            self.mission_recorder.record_sample(sample)

                    self._refresh_connection_state(receive_monotonic_ns)

            except OSError as exc:
                if not self._stop_event.is_set():
                    message = f"UDP telemetry listener error on {self.system_address}: {exc}"
                    logger.error(message)
                    self.state_manager.update(
                        connected=False,
                        status="DISCONNECTED",
                        error=message,
                    )
                    self._stop_event.wait(2.0)
            except Exception as exc:  # Keep the backend alive on receiver errors.
                logger.exception("Unexpected read-only MAVLink receiver error")
                self.state_manager.update(
                    connected=False,
                    status="DISCONNECTED",
                    error=str(exc),
                )
                self._stop_event.wait(2.0)
            finally:
                if current_socket is not None:
                    current_socket.close()
                if self._socket is current_socket:
                    self._socket = None

    def _refresh_connection_state(self, now_monotonic_ns: int | None = None) -> None:
        now = now_monotonic_ns if now_monotonic_ns is not None else monotonic_ns()
        last_valid = self._last_valid_receive_monotonic_ns
        if last_valid is None:
            baseline = self._socket_bound_monotonic_ns
            if baseline is None:
                return
            age_seconds = (now - baseline) / 1_000_000_000
            if age_seconds > self.disconnected_after:
                self.state_manager.update(
                    connected=False,
                    status="DISCONNECTED",
                    error=f"No valid MAVLink telemetry received for {age_seconds:.1f}s",
                )
            elif age_seconds > self.stale_after:
                self.state_manager.update(
                    connected=False,
                    status="STALE",
                    error=f"No valid MAVLink telemetry received for {age_seconds:.1f}s",
                )
            return

        age_seconds = (now - last_valid) / 1_000_000_000
        if age_seconds <= self.stale_after:
            self.state_manager.update(
                connected=True,
                status="CONNECTED",
                error=None,
            )
        elif age_seconds <= self.disconnected_after:
            self.state_manager.update(
                connected=False,
                status="STALE",
                error=f"No valid MAVLink telemetry received for {age_seconds:.1f}s",
            )
        else:
            self.state_manager.update(
                connected=False,
                status="DISCONNECTED",
                error=f"No valid MAVLink telemetry received for {age_seconds:.1f}s",
            )

    def _handle_message(
        self,
        message: Any,
        receive_timestamp_ns: int | None = None,
        receive_monotonic_ns: int | None = None,
    ) -> TelemetrySample | None:
        message_type = self._message_type(message)
        if message_type == "BAD_DATA":
            return None

        receive_timestamp_ns = receive_timestamp_ns or time_ns()
        receive_monotonic_ns = receive_monotonic_ns or monotonic_ns()
        source_time = self._time_normalizer.normalize(message)
        system_id = self._source_id(message, "get_srcSystem")
        component_id = self._source_id(message, "get_srcComponent")

        self._last_valid_receive_monotonic_ns = receive_monotonic_ns
        if message_type == "HEARTBEAT":
            self._last_heartbeat = receive_timestamp_ns / 1_000_000_000

        state_updates: dict[str, Any] = {
            "connected": True,
            "status": "CONNECTED",
            "error": None,
            "last_update": receive_timestamp_ns / 1_000_000_000,
            "receive_timestamp": receive_timestamp_ns,
            "source_timestamp": source_time.timestamp_ns,
            "source_timestamp_raw": source_time.raw_value,
            "source_clock_domain": source_time.clock_domain,
            "source_time_valid": source_time.valid,
            "last_message_type": message_type,
        }
        payload: dict[str, Any]

        if message_type == "HEARTBEAT":
            mode = None
            try:
                mode = mavutil.mode_string_v10(message)
            except Exception:
                mode = str(getattr(message, "custom_mode", "UNKNOWN"))
            armed = bool(
                getattr(message, "base_mode", 0)
                & mavlink.MAV_MODE_FLAG_SAFETY_ARMED
            )
            state_updates.update(armed=armed, flight_mode=mode)
            payload = {
                "armed": armed,
                "flight_mode": mode,
                "type": getattr(message, "type", None),
                "autopilot": getattr(message, "autopilot", None),
                "system_status": getattr(message, "system_status", None),
            }

        elif message_type == "GLOBAL_POSITION_INT":
            lat = self._scaled(getattr(message, "lat", None), 1e7)
            lng = self._scaled(getattr(message, "lon", None), 1e7)
            alt_amsl = self._scaled(getattr(message, "alt", None), 1000.0)
            alt = self._scaled(getattr(message, "relative_alt", None), 1000.0)
            state_updates.update(lat=lat, lng=lng, alt_amsl=alt_amsl, alt=alt)
            payload = {
                "latitude": lat,
                "longitude": lng,
                "relative_altitude": alt,
                "absolute_altitude": alt_amsl,
                "vx": getattr(message, "vx", None),
                "vy": getattr(message, "vy", None),
                "vz": getattr(message, "vz", None),
                "heading_cdeg": getattr(message, "hdg", None),
            }

        elif message_type == "ATTITUDE":
            roll = round(math.degrees(float(message.roll)), 2)
            pitch = round(math.degrees(float(message.pitch)), 2)
            yaw = round(math.degrees(float(message.yaw)), 2)
            state_updates.update(roll_deg=roll, pitch_deg=pitch, yaw_deg=yaw)
            payload = {
                "roll_deg": roll,
                "pitch_deg": pitch,
                "yaw_deg": yaw,
                "roll_speed_rad_s": getattr(message, "rollspeed", None),
                "pitch_speed_rad_s": getattr(message, "pitchspeed", None),
                "yaw_speed_rad_s": getattr(message, "yawspeed", None),
            }

        elif message_type == "ATTITUDE_QUATERNION":
            quaternion = [
                float(getattr(message, field, 0.0))
                for field in ("q1", "q2", "q3", "q4")
            ]
            state_updates["quaternion"] = quaternion
            payload = {
                "quaternion": quaternion,
                "roll_speed_rad_s": getattr(message, "rollspeed", None),
                "pitch_speed_rad_s": getattr(message, "pitchspeed", None),
                "yaw_speed_rad_s": getattr(message, "yawspeed", None),
            }

        elif message_type == "VFR_HUD":
            airspeed = float(message.airspeed)
            groundspeed = float(message.groundspeed)
            heading = float(message.heading)
            climb = float(message.climb)
            state_updates.update(
                airspeed_m_s=airspeed,
                groundspeed_m_s=groundspeed,
                heading_deg=heading,
                v_speed_m_s=climb,
            )
            payload = {
                "airspeed_m_s": airspeed,
                "ground_speed_m_s": groundspeed,
                "heading_deg": heading,
                "vertical_speed_m_s": climb,
            }

        elif message_type in {"SYS_STATUS", "BATTERY_STATUS"}:
            battery_remaining = getattr(message, "battery_remaining", None)
            battery_percent = None
            if battery_remaining is not None and int(battery_remaining) >= 0:
                battery_percent = float(battery_remaining)
                state_updates["battery_percent"] = battery_percent
            if message_type == "SYS_STATUS":
                self._update_prearm_health(message)
            payload = {
                "battery_percent": battery_percent,
                "voltage_battery": getattr(message, "voltage_battery", None),
                "current_battery": getattr(message, "current_battery", None),
            }

        elif message_type in {"GPS_RAW_INT", "GPS2_RAW"}:
            gps_fix = self._int_or_none(getattr(message, "fix_type", None))
            satellites = self._int_or_none(
                getattr(message, "satellites_visible", None)
            )
            state_updates.update(
                gps_fix=gps_fix,
                satellites_visible=satellites,
            )
            payload = {
                "gps_fix": gps_fix,
                "satellites_visible": satellites,
                "hdop": getattr(message, "eph", None),
                "vdop": getattr(message, "epv", None),
                "velocity_cm_s": getattr(message, "vel", None),
            }

        elif message_type == "SYSTEM_TIME":
            payload = {
                "time_unix_usec": getattr(message, "time_unix_usec", None),
                "time_boot_ms": getattr(message, "time_boot_ms", None),
            }

        elif message_type == "EKF_STATUS_REPORT":
            values = {
                "ekf_velocity": float(getattr(message, "velocity_variance", 0.0)),
                "ekf_pos_horiz": float(getattr(message, "pos_horiz_variance", 0.0)),
                "ekf_pos_vert": float(getattr(message, "pos_vert_variance", 0.0)),
                "ekf_compass": float(getattr(message, "compass_variance", 0.0)),
                "ekf_terrain": float(getattr(message, "terrain_alt_variance", 0.0)),
            }
            state_updates.update(values)
            payload = values

        elif message_type == "VIBRATION":
            values = {
                "vibration_x": float(message.vibration_x),
                "vibration_y": float(message.vibration_y),
                "vibration_z": float(message.vibration_z),
                "vibration_clip0": int(message.clipping_0),
                "vibration_clip1": int(message.clipping_1),
                "vibration_clip2": int(message.clipping_2),
            }
            state_updates.update(values)
            payload = values

        elif message_type == "STATUSTEXT":
            text = self._decode_text(getattr(message, "text", ""))
            message_type_name = _SEVERITY_NAMES.get(
                int(getattr(message, "severity", 6)), "INFO"
            )
            formatted = f"[{message_type_name}] {text}"
            state_updates.update(
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
            payload = {
                "text": text,
                "severity": message_type_name,
            }

        else:
            payload = self._safe_message_dict(message)

        self.state_manager.update(**state_updates)
        state = self.state_manager.get()
        sample = TelemetrySample(
            mission_id=state.mission_id,
            source_timestamp=source_time.timestamp_ns,
            source_timestamp_raw=source_time.raw_value,
            source_clock_domain=source_time.clock_domain,
            receive_timestamp=receive_timestamp_ns,
            receive_monotonic_ns=receive_monotonic_ns,
            source_time_valid=source_time.valid,
            message_type=message_type,
            system_id=system_id,
            component_id=component_id,
            payload=payload,
        )
        if self.telemetry_observer:
            try:
                self.telemetry_observer(sample)
            except Exception:
                # Optional live consumers must never stop the receive-only
                # MAVLink loop.
                logger.exception("Ignoring telemetry observer failure")
        return sample

    def _update_prearm_health(self, message: Any) -> None:
        health = int(getattr(message, "onboard_control_sensors_health", 0))
        position_health = health & (
            mavlink.MAV_SYS_STATUS_SENSOR_GPS
            | mavlink.MAV_SYS_STATUS_SENSOR_VISION_POSITION
        )
        self.state_manager.update_prearm_health(
            is_gyrometer_calibration_ok=bool(
                health & mavlink.MAV_SYS_STATUS_SENSOR_3D_GYRO
            ),
            is_accelerometer_calibration_ok=bool(
                health & mavlink.MAV_SYS_STATUS_SENSOR_3D_ACCEL
            ),
            is_magnetometer_calibration_ok=bool(
                health & mavlink.MAV_SYS_STATUS_SENSOR_3D_MAG
            ),
            is_local_position_ok=bool(position_health),
            is_global_position_ok=bool(health & mavlink.MAV_SYS_STATUS_SENSOR_GPS),
            is_home_position_ok=bool(health & mavlink.MAV_SYS_STATUS_SENSOR_GPS),
            is_armable=bool(health & mavlink.MAV_SYS_STATUS_PREARM_CHECK),
        )

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

    @staticmethod
    def _message_type(message: Any) -> str:
        try:
            return str(message.get_type())
        except Exception:
            return type(message).__name__.upper()

    @staticmethod
    def _source_id(message: Any, method_name: str) -> int | None:
        try:
            value = getattr(message, method_name)()
            return int(value) if value is not None else None
        except Exception:
            return None

    @classmethod
    def _safe_message_dict(cls, message: Any) -> dict[str, Any]:
        try:
            raw = message.to_dict()
        except Exception:
            return {"message_type": cls._message_type(message)}
        return cls._json_safe(raw)

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").rstrip("\x00")
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        return str(value)

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
