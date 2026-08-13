from flask import Blueprint, Response, jsonify, request

from app.services.mission_planner_adapter import MissionPlannerAdapter, MissionPlannerBridgeError
from app.services.flight_recorder import FlightRecorder, FlightRecorderError
from app.services.vision_overlay import VisionOverlayError, VisionOverlayStore


api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
_adapter: MissionPlannerAdapter | None = None
_flight_recorder: FlightRecorder | None = None
_vision_overlay_store: VisionOverlayStore | None = None


def init_api_v1_routes(adapter: MissionPlannerAdapter):
    global _adapter, _flight_recorder, _vision_overlay_store
    _adapter = adapter
    _flight_recorder = FlightRecorder(adapter.snapshot)
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


@api_v1_bp.route("/camera/status", methods=["GET"])
def camera_status():
    return jsonify({"ok": True, **_get_flight_recorder().status()})


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


@api_v1_bp.route("/camera/preview-source", methods=["POST"])
def set_camera_preview_source():
    payload = request.get_json(silent=True) or {}
    try:
        state = _get_flight_recorder().set_preview_source(payload.get("source"))
        # The newest B0249 overlay may belong to a frame from before the
        # selector transition. Require a fresh detector payload before the UI
        # draws boxes again after switching back to digital.
        _get_vision_overlay_store().clear()
        return jsonify({"ok": True, **state})
    except FlightRecorderError as exc:
        return jsonify({"ok": False, "error": str(exc), **_get_flight_recorder().status()}), 409


@api_v1_bp.route("/detection/overlay", methods=["GET"])
def latest_detection_overlay():
    """Return the latest short-lived bbox overlay for the low-res preview."""

    return jsonify(_get_vision_overlay_store().latest())


@api_v1_bp.route("/detection/overlay", methods=["POST"])
def ingest_detection_overlay():
    """Accept per-frame YOLO/SAHI boxes without invoking the priority agent."""

    payload = request.get_json(silent=True)
    try:
        telemetry = _get_adapter().snapshot()
        return jsonify(_get_vision_overlay_store().ingest(payload, telemetry=telemetry)), 202
    except VisionOverlayError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_v1_bp.route("/recordings/status", methods=["GET"])
def recording_status():
    return jsonify({"ok": True, **_get_flight_recorder().status()})


@api_v1_bp.route("/recordings/start", methods=["POST"])
def start_recording():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, **_get_flight_recorder().start(payload.get("label"))}), 202
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
    """
    Ingest detection data from CV (Jetson/Mock).
    ---
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            detection_id:
              type: string
              example: "DET-20260728-001"
            timestamp:
              type: string
              example: "2026-07-28T15:30:00Z"
            drone_id:
              type: string
              example: "BENGAWAN-UAV-01"
            reconstructed_location:
              type: object
              properties:
                latitude:
                  type: number
                longitude:
                  type: number
                estimated_margin_error_m:
                  type: number
            detection_data:
              type: object
              properties:
                class:
                  type: string
                count:
                  type: integer
                confidence_avg:
                  type: number
    responses:
      200:
        description: Detection ingested successfully
      400:
        description: Invalid payload
    """
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "Invalid JSON payload"}), 400
        
    # TODO: Phase 3 LLM trigger goes here.
    
    # 1. Fetch telemetry state for context aggregation
    telemetry_state = _get_adapter().snapshot()
    
    # 2. Reconstruct Coordinate if payload missing or dummy
    from app.services.geotagging import estimate_target_gps
    
    cv_payload = dict(payload)
    recon = cv_payload.get("reconstructed_location", {})
    # if it's dummy or missing, recalculate
    if not recon or recon.get("latitude") == 0.0 or recon.get("latitude") is None:
        det_data = cv_payload.get("detection_data", {})
        if "bbox" in det_data:
            # Assuming bbox is [x1, y1, x2, y2]
            bbox = det_data["bbox"]
            u_c = (bbox[0] + bbox[2]) / 2.0
            v_c = (bbox[1] + bbox[3]) / 2.0
            
            tel = telemetry_state.get("telemetry", {})
            lat = tel.get("lat")
            lng = tel.get("lng")
            alt_m = tel.get("relative_alt")
            roll = tel.get("roll_deg")
            pitch = tel.get("pitch_deg")
            yaw = tel.get("yaw_deg")
            
            if all(v is not None for v in [lat, lng, alt_m, roll, pitch, yaw]):
                gps = estimate_target_gps(
                    u_c, v_c, 1920, 1080, # default 1080p assumption if not provided
                    lat, lng, alt_m, roll, pitch, yaw
                )
                if gps:
                    cv_payload["reconstructed_location"] = {
                        "latitude": gps[0],
                        "longitude": gps[1],
                        "estimated_margin_error_m": 5.0
                    }

    # 3. Aggregate data
    ingested_data = {
        "cv_payload": cv_payload,
        "telemetry_context": telemetry_state
    }
    
    print("\n" + "="*50)
    print("[AI AGENT INGESTION] New Detection Received!")
    print(f"Target ID: {payload.get('detection_id')}")
    print(f"Location: {payload.get('reconstructed_location')}")
    print(f"Drone Altitude: {telemetry_state.get('altitude')}m")
    print("="*50 + "\n")
    
    # 3. Trigger Priority Agent LLM Evaluation
    from app.agents.priority_agent import evaluate_detection
    ai_decision = evaluate_detection(ingested_data)
    
    # 4. Trigger Dispatcher if emergency
    priority_level = ai_decision.get("priority_level", "")
    if priority_level in ["HIGH", "CRITICAL"]:
        from app.agents.telegram_dispatcher import send_telegram_alert
        from app.agents.notion_dispatcher import send_notion_task
        send_telegram_alert(ai_decision, payload)
        send_notion_task(ai_decision, payload)
    
    return jsonify({
        "ok": True, 
        "message": "Detection ingested and evaluated", 
        "data": ingested_data,
        "ai_decision": ai_decision
    })
