"""Dataclasses for canonical telemetry, state, commands, and errors."""

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class PreArmHealth:
    """Individual health subsystem statuses from MAVSDK telemetry.health()"""
    is_gyrometer_calibration_ok: bool = False
    is_accelerometer_calibration_ok: bool = False
    is_magnetometer_calibration_ok: bool = False
    is_local_position_ok: bool = False
    is_global_position_ok: bool = False
    is_home_position_ok: bool = False
    is_armable: bool = False

    def to_dict(self):
        return asdict(self)

    def summary_lines(self) -> list[str]:
        """Return human-readable list of failing checks."""
        checks = [
            (self.is_gyrometer_calibration_ok,       "Gyro calibration"),
            (self.is_accelerometer_calibration_ok,    "Accelerometer calibration"),
            (self.is_magnetometer_calibration_ok,     "Magnetometer calibration"),
            (self.is_local_position_ok,               "Local position estimate"),
            (self.is_global_position_ok,              "Global position (GPS)"),
            (self.is_home_position_ok,                "Home position"),
        ]
        return [name for ok, name in checks if not ok]


@dataclass
class TelemetryState:
    """Latest telemetry projection consumed by the existing web UI.

    This remains a snapshot.  Per-message timing and payload provenance live in
    :class:`TelemetrySample` so fields from different MAVLink messages are not
    presented as one measurement taken at the same source time.
    """

    connected: bool = False
    status: str = "DISCONNECTED"  # CONNECTED, STALE, DISCONNECTED, CONNECTING
    lat: Optional[float] = None
    lng: Optional[float] = None
    alt: Optional[float] = None
    alt_amsl: Optional[float] = None
    armed: Optional[bool] = None
    flight_mode: Optional[str] = None
    battery_percent: Optional[float] = None
    status_text: Optional[str] = None
    status_text_type: Optional[str] = None
    prearm_message: Optional[str] = None
    
    # HUD Expansion
    roll_deg: Optional[float] = None
    pitch_deg: Optional[float] = None
    yaw_deg: Optional[float] = None
    heading_deg: Optional[float] = None
    airspeed_m_s: Optional[float] = None
    groundspeed_m_s: Optional[float] = None
    v_speed_m_s: Optional[float] = None

    # EKF & Vibration
    ekf_velocity: float = 0.0
    ekf_pos_horiz: float = 0.0
    ekf_pos_vert: float = 0.0
    ekf_compass: float = 0.0
    ekf_terrain: float = 0.0
    
    vibration_x: float = 0.0
    vibration_y: float = 0.0
    vibration_z: float = 0.0
    vibration_clip0: int = 0
    vibration_clip1: int = 0
    vibration_clip2: int = 0

    last_update: Optional[float] = None
    receive_timestamp: Optional[int] = None
    source_timestamp: Optional[int] = None
    source_timestamp_raw: Optional[int | float] = None
    source_clock_domain: Optional[str] = None
    source_time_valid: bool = False
    last_message_type: Optional[str] = None
    gps_fix: Optional[int] = None
    satellites_visible: Optional[int] = None
    quaternion: Optional[list[float]] = None
    mission_id: Optional[str] = None
    error: Optional[str] = None
    source: str = "mavlink-udp-readonly"
    system_address: str = "udpin://127.0.0.1:14551"

    def to_dict(self):
        return asdict(self)


@dataclass
class TelemetrySample:
    """One normalized MAVLink message/sample.

    ``source_timestamp`` is normalized to UTC nanoseconds only when
    ``source_time_valid`` is true.  ``source_timestamp_raw`` and
    ``source_clock_domain`` preserve the original source clock otherwise.
    ``receive_timestamp`` is always Ground wall-clock UTC nanoseconds when the
    packet was received; it is never used as a silent source-time substitute.
    """

    schema_version: int = 1
    mission_id: Optional[str] = None
    source_timestamp: Optional[int] = None
    source_timestamp_raw: Optional[int | float] = None
    source_clock_domain: Optional[str] = None
    receive_timestamp: Optional[int] = None
    receive_monotonic_ns: Optional[int] = None
    source_time_valid: bool = False
    message_type: str = ""
    system_id: Optional[int] = None
    component_id: Optional[int] = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommandResponse:
    ok: bool
    command: str
    command_id: str
    ts: float
    message: Optional[str] = None
    error_code: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}
