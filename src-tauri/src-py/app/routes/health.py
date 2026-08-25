from flask import Blueprint, jsonify
from app.utils.state import StateManager

health_bp = Blueprint("health", __name__)
_state_manager: StateManager | None = None

def init_health_routes(state_manager: StateManager):
    global _state_manager
    _state_manager = state_manager

@health_bp.route("/health", methods=["GET"])
def health():
    if _state_manager is None:
        return jsonify({"status": "error", "message": "Health manager not initialized"}), 500
        
    state = _state_manager.get()
    return jsonify({
        "connected": state.connected,
        "status": state.status,
        "stale": state.status == "STALE",
        "disconnected": state.status in {"DISCONNECTED", "OFFLINE"},
        "error": state.error,
        "last_update": state.last_update,
        "receive_timestamp": state.receive_timestamp,
        "source_timestamp": state.source_timestamp,
        "source_time_valid": state.source_time_valid,
        "last_message_type": state.last_message_type,
        "mission_id": state.mission_id,
        "system_address": state.system_address,
    })


@health_bp.route("/health/prearm", methods=["GET"])
def prearm_check():
    """Return full pre-arm health diagnostics.

    Response includes:
      - health: MAVSDK telemetry.health() subsystem flags
      - is_armable: overall armability (from the FC)
      - failing_checks: human-readable list of subsystems that are NOT OK
      - recent_prearm_messages: STATUSTEXT entries containing 'PreArm'
      - recent_status_texts: last 20 STATUSTEXT entries (any type)
      - telemetry_snapshot: key telemetry values for context
    """
    if _state_manager is None:
        return jsonify({"status": "error", "message": "Health manager not initialized"}), 500

    state = _state_manager.get()
    prearm = _state_manager.get_prearm_health()
    failing = prearm.summary_lines()

    return jsonify({
        "connected": state.connected,
        "armed": state.armed,
        "flight_mode": state.flight_mode,

        "is_armable": prearm.is_armable,
        "health": prearm.to_dict(),
        "failing_checks": failing,
        "all_checks_ok": len(failing) == 0 and prearm.is_armable,

        "recent_prearm_messages": _state_manager.get_prearm_texts(),
        "recent_status_texts": _state_manager.get_status_text_history(),

        "telemetry_snapshot": {
            "lat": state.lat,
            "lng": state.lng,
            "alt": state.alt,
            "battery_percent": state.battery_percent,
            "heading_deg": state.heading_deg,
            "ekf_velocity": state.ekf_velocity,
            "ekf_pos_horiz": state.ekf_pos_horiz,
            "ekf_pos_vert": state.ekf_pos_vert,
            "ekf_compass": state.ekf_compass,
        },
    })
