from flask import Blueprint, Response, jsonify, request

from app.contracts import ContractError, validate_detection_event
from app.persistence import Database
from app.services.mission_planner_adapter import MissionPlannerAdapter, MissionPlannerBridgeError
from app.services.flight_recorder import FlightRecorder, FlightRecorderError
from app.services.vision_overlay import VisionOverlayError, VisionOverlayStore
from app.services.frame_sync import FrameSyncError, FrameSynchronizer, StreamRegistry


api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
_adapter: MissionPlannerAdapter | None = None
_flight_recorder: FlightRecorder | None = None
_vision_overlay_store: VisionOverlayStore | None = None
_database: Database | None = None


def init_api_v1_routes(adapter: MissionPlannerAdapter, database: Database | None = None):
    global _adapter, _flight_recorder, _vision_overlay_store, _database
    _adapter = adapter
    _database = database
    _flight_recorder = FlightRecorder(
        adapter.snapshot,
        stream_registry=StreamRegistry(),
        synchronizer=FrameSynchronizer(wait_ms=150),
    )
    _vision_overlay_store = VisionOverlayStore()


def _get_adapter():
    if _adapter is None:
        raise RuntimeError("Mission Planner adapter is not initialized")
    return _adapter


def _get_flight_recorder():
    if _flight_recorder is None:
        raise RuntimeError("Flight recorder is not initialized")
    return _flight_recorder


def _get_vision_overlay_store():
    if _vision_overlay_store is None:
        raise RuntimeError("Vision overlay store is not initialized")
    return _vision_overlay_store


def _get_database() -> Database:
    if _database is None:
        raise RuntimeError("Database is not initialized")
    return _database


def get_vision_service():
    return _get_flight_recorder().vision_service


@api_v1_bp.route("/camera/status", methods=["GET"])
def camera_status():
    return jsonify({"ok": True, **_get_flight_recorder().status()})


@api_v1_bp.route("/session/verify", methods=["POST"])
def verify_operator_session():
    return jsonify({"ok": True, "role": "operator"})


@api_v1_bp.route("/camera/start", methods=["POST"])
def start_camera():
    try:
        return jsonify({"ok": True, **_get_flight_recorder().start_camera()}), 202
    except FlightRecorderError as exc:
        return jsonify({"ok": False, "error": str(exc), **_get_flight_recorder().status()}), 503


@api_v1_bp.route("/camera/stop", methods=["POST"])
def stop_camera():
    try:
        return jsonify({"ok": True, **_get_flight_recorder().stop_camera()})
    except FlightRecorderError as exc:
        return jsonify({"ok": False, "error": str(exc), **_get_flight_recorder().status()}), 409


@api_v1_bp.route("/camera/preview", methods=["GET"])
def camera_preview():
    return Response(
        _get_flight_recorder().preview_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "X-Accel-Buffering": "no",
        },
    )


@api_v1_bp.route("/detection/overlay", methods=["GET"])
def latest_detection_overlay():
    """Return the latest short-lived bbox overlay for the low-res preview."""

    return jsonify(_get_vision_overlay_store().latest())


@api_v1_bp.route("/detection/overlay", methods=["POST"])
def ingest_detection_overlay():
    """Accept exact v2 frame metadata without invoking reporting."""

    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict) or payload.get("schema_version") != "2.0":
            raise FrameSyncError("detection overlay must use schema_version 2.0")
        accepted = _get_flight_recorder().ingest_frame_metadata(payload)
        return jsonify({"ok": True, "accepted": accepted}), 202
    except (FrameSyncError, FlightRecorderError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_v1_bp.route("/stream/register", methods=["POST"])
def register_stream():
    payload = request.get_json(silent=True)
    try:
        return jsonify({"ok": True, **_get_flight_recorder().register_stream(payload)}), 202
    except (FrameSyncError, FlightRecorderError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_v1_bp.route("/recordings/status", methods=["GET"])
def recording_status():
    return jsonify({"ok": True, **_get_flight_recorder().status()})


@api_v1_bp.route("/recordings/start", methods=["POST"])
def start_recording():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({
            "ok": True,
            **_get_flight_recorder().start(payload.get("label"), payload.get("mission_id")),
        }), 202
    except FlightRecorderError as exc:
        return jsonify({"ok": False, "error": str(exc), **_get_flight_recorder().status()}), 409


@api_v1_bp.route("/recordings/stop", methods=["POST"])
def stop_recording():
    try:
        return jsonify({"ok": True, **_get_flight_recorder().stop()})
    except FlightRecorderError as exc:
        return jsonify({"ok": False, "error": str(exc), **_get_flight_recorder().status()}), 409


@api_v1_bp.route("/health", methods=["GET"])
def health():
    """
    Get system health and status.
    ---
    responses:
      200:
        description: Returns the connection status and address
    """
    return jsonify(_get_adapter().health())


@api_v1_bp.route("/telemetry", methods=["GET"])
def telemetry():
    """
    Get full flight telemetry.
    ---
    responses:
      200:
        description: Returns current position, attitude, speed, and battery
    """
    return jsonify(_get_adapter().snapshot())


@api_v1_bp.route("/mission", methods=["GET"])
def mission():
    """
    Get current mission progress.
    ---
    responses:
      200:
        description: Returns mission waypoints and progress
      502:
        description: Mission Planner connection error
    """
    try:
        return jsonify(_get_adapter().mission())
    except MissionPlannerBridgeError as exc:
        return jsonify(exc.payload), exc.status_code
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "waypoints": [], "count": 0}), 502


@api_v1_bp.route("/messages", methods=["GET"])
def messages():
    try:
        return jsonify(_get_adapter().messages())
    except MissionPlannerBridgeError as exc:
        return jsonify(exc.payload), exc.status_code
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "messages": [], "count": 0}), 502


@api_v1_bp.route("/commands/set-flight-mode", methods=["POST"])
def set_flight_mode():
    """
    Change the UAV flight mode.
    ---
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            mode:
              type: string
              example: "GUIDED"
    responses:
      200:
        description: Command accepted
      400:
        description: Invalid mode
      502:
        description: MAVLink error
    """
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
    except MissionPlannerBridgeError as exc:
        return jsonify(exc.payload), exc.status_code
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@api_v1_bp.route("/commands/set-current-waypoint", methods=["POST"])
def set_current_waypoint():
    payload = request.get_json(silent=True) or {}
    try:
        seq = int(payload.get("seq"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "seq is required and must be an integer"}), 400
    if seq < 0:
        return jsonify({"ok": False, "error": "seq must be zero or greater"}), 400
    try:
        response, status = _get_adapter().send_command(
            "set-current-waypoint",
            {"request_id": payload.get("request_id"), "seq": seq},
        )
        return jsonify(response), status
    except MissionPlannerBridgeError as exc:
        return jsonify(exc.payload), exc.status_code
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
    except MissionPlannerBridgeError as exc:
        return jsonify(exc.payload), exc.status_code
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@api_v1_bp.route("/commands/arm", methods=["POST"])
def arm():
    """
    Arm the vehicle.
    ---
    responses:
      200:
        description: Vehicle armed successfully
    """
    return _proxy_simple_command("arm")


@api_v1_bp.route("/commands/disarm", methods=["POST"])
def disarm():
    """
    Disarm the vehicle.
    ---
    responses:
      200:
        description: Vehicle disarmed successfully
    """
    return _proxy_simple_command("disarm")


@api_v1_bp.route("/commands/reboot", methods=["POST"])
def reboot():
    """
    Reboot the flight controller.
    ---
    responses:
      200:
        description: Vehicle rebooted
    """
    return _proxy_simple_command("reboot")


@api_v1_bp.route("/detection/ingest", methods=["POST"])
def ingest_detection():
    """Validate and persist one canonical event without invoking reporting."""

    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict):
            raise ContractError("request body must be a JSON object")
        normalized = validate_detection_event(payload)
        created = _get_database().insert_detection(normalized)
    except ContractError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({
        "ok": True,
        "accepted": created,
        "duplicate": not created,
        "detection_id": normalized["detection_id"],
        "reporting_state": "PENDING_BATCH_9",
    }), 202 if created else 200
