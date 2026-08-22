from flask import Blueprint, jsonify

from app.config import MAVLINK_UDP_HOST, MAVLINK_UDP_PORT, WEBAPP_READ_ONLY


capabilities_bp = Blueprint("capabilities", __name__)


@capabilities_bp.route("/capabilities", methods=["GET"])
def capabilities():
    """Expose the control boundary so the frontend can disable controls."""
    return jsonify({
        "ok": True,
        "read_only": WEBAPP_READ_ONLY,
        "control_owner": "QGroundControl",
        "telemetry": {
            "enabled": True,
            "transport": "mavlink-udp-receive-only",
            "host": MAVLINK_UDP_HOST,
            "port": MAVLINK_UDP_PORT,
        },
        "commands": {
            "enabled": False,
            "reason": "Vehicle commands are intentionally disabled in the webapp; use QGroundControl on UDP 14550",
        },
        "missions": {
            "enabled": False,
            "reason": "Mission operations are intentionally disabled in the webapp; use QGroundControl",
        },
        "parameters": {
            "read": False,
            "write": False,
        },
    })
