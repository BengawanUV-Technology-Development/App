import base64
import binascii
import os
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file

from app.contracts import ContractError, validate_detection_event, validate_normalized_xyxy
from app.persistence import Database
# MissionPlannerAdapter replaced by MavlinkUdpAdapter (read-only); bridge error kept for compat.
from app.services.mission_planner_adapter import MissionPlannerBridgeError
from app.services.flight_recorder import FlightRecorder, FlightRecorderError
from app.services.vision_overlay import VisionOverlayError, VisionOverlayStore
from app.services.browser_render_metrics import BrowserRenderMetrics, BrowserRenderMetricsError
from app.services.frame_sync import FrameSyncError, FrameSynchronizer, StreamRegistry


# Where jetson/generate_detection_snapshots.py's jpegs land once ingested
# (see docs/post-flight-detection-snapshots.md). Same runtime/ convention
# as BUV_DATABASE_PATH in main.py.
POSTFLIGHT_SNAPSHOT_DIR = Path(
    os.getenv(
        "BUV_POSTFLIGHT_SNAPSHOT_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "runtime" / "postflight_snapshots"),
    )
).expanduser()

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
_adapter = None  # MavlinkUdpAdapter (or legacy MissionPlannerAdapter) – duck-typed
_flight_recorder: FlightRecorder | None = None
_vision_overlay_store: VisionOverlayStore | None = None
_database: Database | None = None
_browser_render_metrics: BrowserRenderMetrics | None = None


def init_api_v1_routes(adapter, database: Database | None = None):
    """Initialize route-level singletons.

    *adapter* may be a MavlinkUdpAdapter (read-only) or the legacy
    MissionPlannerAdapter; both expose the same snapshot/health/mission
    /messages API surface.
    """
    global _adapter, _flight_recorder, _vision_overlay_store, _database, _browser_render_metrics
    _adapter = adapter
    _database = database
    _flight_recorder = FlightRecorder(
        adapter.snapshot,
        stream_registry=StreamRegistry(),
        synchronizer=FrameSynchronizer(),
        telemetry_history=adapter.telemetry_recorder.nearest,
        telemetry_session_start=adapter.telemetry_recorder.start_session,
        telemetry_session_stop=adapter.telemetry_recorder.end_session,
    )
    _vision_overlay_store = VisionOverlayStore()
    _browser_render_metrics = BrowserRenderMetrics()


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


def _get_browser_render_metrics():
    if _browser_render_metrics is None:
        raise RuntimeError("Browser render metrics are not initialized")
    return _browser_render_metrics


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
        return jsonify({**_get_flight_recorder().status(), "ok": False, "error": str(exc)}), 503


@api_v1_bp.route("/camera/stop", methods=["POST"])
def stop_camera():
    try:
        return jsonify({"ok": True, **_get_flight_recorder().stop_camera()})
    except FlightRecorderError as exc:
        # Spread status() FIRST, then the explicit ok/error keys, so the
        # real failure reason isn't silently clobbered by status()'s own
        # "ok"/"error" fields (e.g. a healthy IDLE Jetson response reporting
        # its own "ok": true, "error": null).
        return jsonify({**_get_flight_recorder().status(), "ok": False, "error": str(exc)}), 409


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


@api_v1_bp.route("/live/detections", methods=["GET"])
def live_detections():
    """Raw, un-clustered detection dots for the in-flight map view (last ~20s).

    Meant to be polled frequently while a recording is active so the operator
    can see detection density/noise in real time; the frontend should stop
    polling once the recording ends. See
    docs/post-flight-detection-snapshots.md for the (separate, deduplicated)
    post-flight review pins.
    """

    return jsonify({"ok": True, "detections": _get_flight_recorder().live_detections.snapshot()})


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


@api_v1_bp.route("/vision/metrics", methods=["GET", "POST"])
def vision_metrics():
    if request.method == "GET":
        return jsonify({"ok": True, **_get_browser_render_metrics().snapshot()})
    try:
        return jsonify({"ok": True, **_get_browser_render_metrics().record(request.get_json(silent=True))}), 202
    except BrowserRenderMetricsError as exc:
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
        # Spread status() FIRST, then the explicit ok/error keys, so the
        # real failure reason isn't silently clobbered by status()'s own
        # "ok"/"error" fields (e.g. a healthy IDLE Jetson response reporting
        # its own "ok": true, "error": null).
        return jsonify({**_get_flight_recorder().status(), "ok": False, "error": str(exc)}), 409


@api_v1_bp.route("/recordings/stop", methods=["POST"])
def stop_recording():
    try:
        return jsonify({"ok": True, **_get_flight_recorder().stop()})
    except FlightRecorderError as exc:
        # Spread status() FIRST, then the explicit ok/error keys, so the
        # real failure reason isn't silently clobbered by status()'s own
        # "ok"/"error" fields (e.g. a healthy IDLE Jetson response reporting
        # its own "ok": true, "error": null).
        return jsonify({**_get_flight_recorder().status(), "ok": False, "error": str(exc)}), 409


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


# ---------------------------------------------------------------------------
# POST command endpoints – DISABLED (adapter is read-only via UDP mirror)
# ---------------------------------------------------------------------------
# All MAVLink commands must be sent through Mission Planner or a dedicated
# command channel.  Un-comment these routes only when a writable adapter is
# re-introduced.
#
# @api_v1_bp.route("/commands/set-flight-mode", methods=["POST"])
# def set_flight_mode():
#     payload = request.get_json(silent=True) or {}
#     mode = str(payload.get("mode") or "").strip()
#     if not mode:
#         return jsonify({"ok": False, "error": "mode is required"}), 400
#     try:
#         response, status = _get_adapter().send_command(
#             "set-flight-mode",
#             {"request_id": payload.get("request_id"), "mode": mode},
#         )
#         return jsonify(response), status
#     except MissionPlannerBridgeError as exc:
#         return jsonify(exc.payload), exc.status_code
#     except Exception as exc:
#         return jsonify({"ok": False, "error": str(exc)}), 502

#
# @api_v1_bp.route("/commands/set-current-waypoint", methods=["POST"])
# def set_current_waypoint():
#     payload = request.get_json(silent=True) or {}
#     try:
#         seq = int(payload.get("seq"))
#     except (TypeError, ValueError):
#         return jsonify({"ok": False, "error": "seq is required and must be an integer"}), 400
#     if seq < 0:
#         return jsonify({"ok": False, "error": "seq must be zero or greater"}), 400
#     try:
#         response, status = _get_adapter().send_command(
#             "set-current-waypoint",
#             {"request_id": payload.get("request_id"), "seq": seq},
#         )
#         return jsonify(response), status
#     except MissionPlannerBridgeError as exc:
#         return jsonify(exc.payload), exc.status_code
#     except Exception as exc:
#         return jsonify({"ok": False, "error": str(exc)}), 502
#
# def _proxy_simple_command(command):
#     payload = request.get_json(silent=True) or {}
#     try:
#         response, status = _get_adapter().send_command(
#             command, {"request_id": payload.get("request_id")},
#         )
#         return jsonify(response), status
#     except MissionPlannerBridgeError as exc:
#         return jsonify(exc.payload), exc.status_code
#     except Exception as exc:
#         return jsonify({"ok": False, "error": str(exc)}), 502
#
# @api_v1_bp.route("/commands/arm", methods=["POST"])
# def arm():
#     return _proxy_simple_command("arm")
#
# @api_v1_bp.route("/commands/disarm", methods=["POST"])
# def disarm():
#     return _proxy_simple_command("disarm")
#
# @api_v1_bp.route("/commands/reboot", methods=["POST"])
# def reboot():
#     return _proxy_simple_command("reboot")


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


def _postflight_snapshot_path(detection_id: str) -> Path:
    # detection_id is a UUID validated below, never used to build a path
    # from unsanitized input.
    return POSTFLIGHT_SNAPSHOT_DIR / f"{detection_id}.jpg"


@api_v1_bp.route("/postflight/detections", methods=["POST"])
def ingest_postflight_detection():
    """Receive one hover-preview snapshot from
    jetson/generate_detection_snapshots.py (see
    docs/post-flight-detection-snapshots.md) -- a manifest row plus its
    already-cropped, already-bbox-drawn jpeg, base64-encoded."""

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "request body must be a JSON object"}), 400
    try:
        detection_id = str(uuid.UUID(str(payload.get("detection_id"))))
        mission_id = str(payload["mission_id"])
        if not mission_id.startswith("mission-"):
            raise ContractError("mission_id must start with 'mission-'")
        capture_epoch = int(payload["capture_epoch"])
        frame_id = int(payload["frame_id"])
        label = payload.get("class")
        if not isinstance(label, str) or not label.strip():
            raise ContractError("class must be a non-empty string")
        confidence = payload.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ContractError("confidence must be between 0 and 1")
        bbox = validate_normalized_xyxy(payload.get("bbox_normalized_xyxy"))
        coordinate = payload.get("coordinate")
        if not isinstance(coordinate, dict) or "status" not in coordinate:
            raise ContractError("coordinate must be a dict with a status")
        capture_utc_ns = payload.get("capture_utc_ns")
        # Cross-time/within-frame dedup metadata from
        # generate_detection_snapshots.py's clustering pass (see
        # docs/post-flight-detection-snapshots.md). Optional: older callers
        # (or the AI-agent dummy test) may not send them.
        cluster_id = payload.get("cluster_id")
        if cluster_id is not None and not isinstance(cluster_id, int):
            raise ContractError("cluster_id must be an integer")
        cluster_size = payload.get("cluster_size")
        if cluster_size is not None and not isinstance(cluster_size, int):
            raise ContractError("cluster_size must be an integer")
        is_representative = payload.get("is_representative")
        if is_representative is not None and not isinstance(is_representative, bool):
            raise ContractError("is_representative must be a boolean")
        snapshot_b64 = payload.get("snapshot_jpeg_base64")
        if not isinstance(snapshot_b64, str) or not snapshot_b64:
            raise ContractError("snapshot_jpeg_base64 is required")
        jpeg_bytes = base64.b64decode(snapshot_b64, validate=True)
        if not (jpeg_bytes.startswith(b"\xff\xd8") and jpeg_bytes.endswith(b"\xff\xd9")):
            raise ContractError("snapshot_jpeg_base64 does not decode to a JPEG")
    except (KeyError, TypeError, ValueError, ContractError, binascii.Error) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    POSTFLIGHT_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = _postflight_snapshot_path(detection_id)
    snapshot_path.write_bytes(jpeg_bytes)
    created = _get_database().insert_postflight_detection(
        {
            "detection_id": detection_id, "mission_id": mission_id, "capture_epoch": capture_epoch,
            "frame_id": frame_id, "class": label.strip(), "confidence": float(confidence),
            "bbox_normalized_xyxy": list(bbox), "coordinate": coordinate, "capture_utc_ns": capture_utc_ns,
            "cluster_id": cluster_id, "cluster_size": cluster_size, "is_representative": is_representative,
        },
        str(snapshot_path),
    )
    return jsonify({"ok": True, "accepted": created, "duplicate": not created, "detection_id": detection_id}), 202 if created else 200


@api_v1_bp.route("/postflight/detections", methods=["GET"])
def list_postflight_detections():
    """Recent post-flight detections for the map's target pins. Never
    includes the jpeg itself -- fetch /postflight/detections/<id>/snapshot
    on hover instead, so this list stays light."""

    mission_id = request.args.get("mission_id")
    limit = request.args.get("limit", default=500, type=int)
    records = _get_database().list_postflight_detections(mission_id=mission_id, limit=limit)
    for record in records:
        record.pop("snapshot_path", None)
    return jsonify({"ok": True, "detections": records})


@api_v1_bp.route("/postflight/detections/<detection_id>/snapshot", methods=["GET"])
def postflight_detection_snapshot(detection_id: str):
    record = _get_database().get_postflight_detection(detection_id)
    if record is None:
        return jsonify({"ok": False, "error": "unknown detection_id"}), 404
    snapshot_path = Path(record["snapshot_path"])
    if not snapshot_path.is_file():
        return jsonify({"ok": False, "error": "snapshot file is missing on disk"}), 404
    return send_file(snapshot_path, mimetype="image/jpeg", max_age=3600)
