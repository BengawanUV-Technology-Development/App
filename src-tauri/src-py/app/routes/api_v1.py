from flask import Blueprint, jsonify, request

from app.services.mission_planner_adapter import MissionPlannerAdapter


api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
_adapter: MissionPlannerAdapter | None = None


def init_api_v1_routes(adapter: MissionPlannerAdapter):
    global _adapter
    _adapter = adapter


def _get_adapter():
    if _adapter is None:
        raise RuntimeError("Mission Planner adapter is not initialized")
    return _adapter


@api_v1_bp.route("/health", methods=["GET"])
def health():
    return jsonify(_get_adapter().health())


@api_v1_bp.route("/telemetry", methods=["GET"])
def telemetry():
    return jsonify(_get_adapter().snapshot())


@api_v1_bp.route("/commands/set-flight-mode", methods=["POST"])
def set_flight_mode():
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode") or "").strip()
    if not mode:
        return jsonify({"ok": False, "error": "mode is required"}), 400
    try:
        response, status = _get_adapter().send_command(
            "set-flight-mode",
            {"request_id": payload.get("request_id"), "mode": mode},
        )
        return jsonify(response), status
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


def _proxy_simple_command(command):
    payload = request.get_json(silent=True) or {}
    try:
        response, status = _get_adapter().send_command(
            command,
            {"request_id": payload.get("request_id")},
        )
        return jsonify(response), status
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@api_v1_bp.route("/commands/arm", methods=["POST"])
def arm():
    return _proxy_simple_command("arm")


@api_v1_bp.route("/commands/disarm", methods=["POST"])
def disarm():
    return _proxy_simple_command("disarm")
