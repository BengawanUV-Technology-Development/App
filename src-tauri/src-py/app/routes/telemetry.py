from flask import Blueprint, jsonify, request
from app.utils.state import StateManager

telemetry_bp = Blueprint("telemetry", __name__)
state_manager: StateManager | None = None

def init_telemetry_routes(state_mgr: StateManager):
    global state_manager
    state_manager = state_mgr

def _get_manager():
    if state_manager is None:
        return None
    return state_manager


@telemetry_bp.route("/telemetry", methods=["GET"])
def get_telemetry():
    manager = _get_manager()
    if not manager:
        return jsonify({"error": "State manager not initialized"}), 500
    return jsonify(manager.get().to_dict())

@telemetry_bp.route("/get-coordinates", methods=["GET"])
def get_coordinates():
    manager = _get_manager()
    if not manager:
        return jsonify({"error": "State manager not initialized"}), 500
    state = manager.get()
    data = {
        "lat": state.lat,
        "lng": state.lng,
        "alt": state.alt,
        "connected": state.connected,
        "last_update": state.last_update,
        "error": state.error,
    }
    return jsonify(data)

