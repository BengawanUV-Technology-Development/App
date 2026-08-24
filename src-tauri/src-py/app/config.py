"""Runtime configuration for the telemetry-only web backend.

The web application deliberately has no serial/MAVSDK connection.  The
router owns the Pixhawk serial link and forwards a copy of MAVLink telemetry
to ``MAVLINK_UDP_PORT``.  Keep the read-only flag as a constant: this build is
not allowed to be turned into a flight-control client through an environment
variable.
"""
import os
from pathlib import Path


def _load_local_env() -> None:
    """Load the optional local camera env without overriding real env vars."""

    root = Path(__file__).resolve().parents[1]
    for path in (root / "camera.env", root / ".camera-agent-token.env"):
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip("\"'")


_load_local_env()


API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "5001"))

MAVLINK_UDP_HOST = os.getenv("MAVLINK_UDP_HOST", "127.0.0.1")
MAVLINK_UDP_PORT = int(os.getenv("MAVLINK_UDP_PORT", "14551"))
MAVLINK_HEARTBEAT_TIMEOUT_SECONDS = float(os.getenv("MAVLINK_HEARTBEAT_TIMEOUT_SECONDS", "5"))
TELEMETRY_LOG_INTERVAL_SECONDS = float(os.getenv("TELEMETRY_LOG_INTERVAL_SECONDS", "1"))

JETSON_RECORDING_AGENT_URL = os.getenv(
    "JETSON_RECORDING_AGENT_URL", "http://100.124.21.25:5101"
).rstrip("/")
JETSON_RECORDING_AGENT_TOKEN = os.getenv("JETSON_RECORDING_AGENT_TOKEN", "").strip()
JETSON_RECORDING_AGENT_TIMEOUT_SECONDS = float(
    os.getenv("JETSON_RECORDING_AGENT_TIMEOUT_SECONDS", "8")
)

# Intentional security boundary.  Do not replace this with an env var: the
# command path belongs to QGroundControl on UDP 14550, not to this web app.
WEBAPP_READ_ONLY = True

DEBUG = os.getenv("DEBUG", "false").lower() == "true"


def mavlink_udp_address() -> str:
    return f"udpin://{MAVLINK_UDP_HOST}:{MAVLINK_UDP_PORT}"
