"""Runtime configuration for the telemetry-only web backend.

The web application deliberately has no serial/MAVSDK connection.  The
router owns the Pixhawk serial link and forwards a copy of MAVLink telemetry
to ``MAVLINK_UDP_PORT``.  Keep the read-only flag as a constant: this build is
not allowed to be turned into a flight-control client through an environment
variable.
"""
import os


API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "5001"))

MAVLINK_UDP_HOST = os.getenv("MAVLINK_UDP_HOST", "127.0.0.1")
MAVLINK_UDP_PORT = int(os.getenv("MAVLINK_UDP_PORT", "14551"))
MAVLINK_HEARTBEAT_TIMEOUT_SECONDS = float(os.getenv("MAVLINK_HEARTBEAT_TIMEOUT_SECONDS", "5"))
TELEMETRY_LOG_INTERVAL_SECONDS = float(os.getenv("TELEMETRY_LOG_INTERVAL_SECONDS", "1"))

# Intentional security boundary.  Do not replace this with an env var: the
# command path belongs to QGroundControl on UDP 14550, not to this web app.
WEBAPP_READ_ONLY = True

DEBUG = os.getenv("DEBUG", "false").lower() == "true"


def mavlink_udp_address() -> str:
    return f"udpin://{MAVLINK_UDP_HOST}:{MAVLINK_UDP_PORT}"
