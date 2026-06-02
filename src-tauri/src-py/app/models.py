"""
Dataclasses for state, requests, responses.
Type-safe schemas untuk telemetry, commands, errors.
"""
from dataclasses import dataclass, asdict, field
from typing import Optional
from datetime import datetime


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
    """Vehicle telemetry state"""
    connected: bool = False
    status: str = "OFFLINE" # OFFLINE, REBOOTING, CONNECTING, ACTIVE
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
    
    status_text: Optional[str] = None
    
    last_update: Optional[float] = None
    error: Optional[str] = None
    source: str = "mavsdk"
    system_address: str = "serial://COM9:115200"

    def to_dict(self):
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
