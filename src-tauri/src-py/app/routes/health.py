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
        "error": state.error,
        "last_update": state.last_update,
        "system_address": state.system_address,
    })

@health_bp.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "Python backend is running",
        "hint": "Use /health, /telemetry, or /command endpoints",
    })