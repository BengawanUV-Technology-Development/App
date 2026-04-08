"""
Dataclasses for state, requests, responses.
Type-safe schemas untuk telemetry, commands, errors.
"""
from dataclasses import dataclass, asdict, field
from typing import Optional
from datetime import datetime


@dataclass
class TelemetryState:
    """Vehicle telemetry state"""
    connected: bool = False
    lat: Optional[float] = None
    lng: Optional[float] = None
    alt: Optional[float] = None
    alt_amsl: Optional[float] = None
    armed: Optional[bool] = None
    flight_mode: Optional[str] = None
    battery_percent: Optional[float] = None
    last_update: Optional[float] = None
    error: Optional[str] = None
    source: str = "mavsdk"
    system_address: str = "serial://COM6:115200"

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
