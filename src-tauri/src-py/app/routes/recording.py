"""Camera-source and Jetson recording controls."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.config import API_PORT
from app.services.camera_stream import CameraStreamError, CameraStreamService
from app.services.jetson_recording import JetsonRecordingClient, JetsonRecordingError
from app.services.mission_telemetry import (
    MissionTelemetryError,
    MissionTelemetryRecorder,
)
from app.utils.state import StateManager


recording_bp = Blueprint("recording", __name__, url_prefix="/api/v1")
_camera_service: CameraStreamService | None = None
_jetson_client: JetsonRecordingClient | None = None
_state_manager: StateManager | None = None
_mission_recorder: MissionTelemetryRecorder | None = None


def init_recording_routes(
    camera_service: CameraStreamService,
    jetson_client: JetsonRecordingClient,
    state_manager: StateManager | None = None,
    mission_recorder: MissionTelemetryRecorder | None = None,
) -> None:
    global _camera_service, _jetson_client, _state_manager, _mission_recorder
    _camera_service = camera_service
    _jetson_client = jetson_client
    _state_manager = state_manager
    _mission_recorder = mission_recorder


def _camera() -> CameraStreamService:
    if _camera_service is None:
        raise RuntimeError("Camera service is not initialized")
    return _camera_service


def _jetson() -> JetsonRecordingClient:
    if _jetson_client is None:
        raise RuntimeError("Jetson recording client is not initialized")
    return _jetson_client


def _mission() -> MissionTelemetryRecorder | None:
    return _mission_recorder


def _source_from_request() -> str:
    payload = request.get_json(silent=True) or {}
    source = payload.get("source", "csi")
    if source not in {"csi", "analog"}:
        raise JetsonRecordingError("source must be csi or analog")
    return source


def _remote_source(source: str) -> str:
    return "analog" if source == "analog" else "digital"


def _combined(remote: dict, source: str | None = None) -> dict:
    result = dict(remote)
    result["camera"] = _camera().status()
    result["source"] = source or (
        "analog" if remote.get("preview_active_source") == "analog" else "csi"
    )
    if _mission() is not None:
        result.update(_mission().status())
    return result


@recording_bp.route("/recordings/status", methods=["GET"])
def recording_status():
    try:
        remote = _jetson().status()
        return jsonify(_combined(remote))
    except JetsonRecordingError as exc:
        local = _mission().status() if _mission() is not None else {}
        return jsonify({
            "ok": False,
            "status": "REMOTE_UNKNOWN",
            "recording": local.get("recording", False),
            "error": str(exc),
            **local,
        }), 503


@recording_bp.route("/recordings/start", methods=["POST"])
def recording_start():
    source = "csi"
    camera_started = False
    mission_started = False
    mission_id = None
    try:
        source = _source_from_request()
        if _mission() is not None:
            mission = _mission().start()
            mission_started = True
            mission_id = mission["mission_id"]
            if _state_manager is not None:
                _state_manager.set_mission_id(mission_id)

        camera = _camera()
        camera.start()
        camera_started = True
        if mission_id:
            remote = _jetson().start(
                label=f"web-{source}",
                video_port=camera.port,
                api_port=API_PORT,
                mission_id=mission_id,
            )
        else:
            # Preserve compatibility with lightweight test doubles and older
            # Jetson clients when mission recording is not configured.
            remote = _jetson().start(
                label=f"web-{source}",
                video_port=camera.port,
                api_port=API_PORT,
            )
        if source == "analog":
            remote = _jetson().set_preview_source("analog")
        return jsonify(_combined(remote, source)), 202
    except (CameraStreamError, JetsonRecordingError, MissionTelemetryError) as exc:
        if camera_started:
            try:
                _camera().stop()
            except CameraStreamError:
                pass
        if mission_started and _mission() is not None:
            _mission().stop(reason="start_failed")
        if _state_manager is not None:
            _state_manager.set_mission_id(None)
        return jsonify({
            "ok": False,
            "status": "FAILED",
            "recording": False,
            "source": source,
            "error": str(exc),
        }), 503


@recording_bp.route("/recordings/stop", methods=["POST"])
def recording_stop():
    remote = None
    failure: Exception | None = None
    completed_mission = None
    try:
        remote = _jetson().stop()
        camera = _camera()
        camera.stop()
    except (CameraStreamError, JetsonRecordingError) as exc:
        failure = exc

    if _mission() is not None and _mission().active:
        completed_mission = _mission().stop(
            reason="remote_stop_failed" if failure else "completed"
        )
    if _state_manager is not None:
        _state_manager.set_mission_id(None)

    if failure is not None:
        response = {
            "ok": False,
            "status": "FAILED",
            "recording": False,
            "error": str(failure),
            **(_mission().status() if _mission() is not None else {}),
        }
        if completed_mission:
            response.update(
                {
                    "completed_mission_id": completed_mission["mission_id"],
                    "completed_telemetry_log_path": completed_mission["path"],
                    "completed_telemetry_dropped_samples": completed_mission[
                        "dropped_samples"
                    ],
                }
            )
        return jsonify(response), 409

    response = _combined(remote or {})
    if completed_mission:
        response.update(
            {
                "completed_mission_id": completed_mission["mission_id"],
                "completed_telemetry_log_path": completed_mission["path"],
                "completed_telemetry_dropped_samples": completed_mission[
                    "dropped_samples"
                ],
            }
        )
    return jsonify(response)


@recording_bp.route("/camera/source", methods=["GET", "POST"])
def camera_source():
    try:
        if request.method == "POST":
            source = _source_from_request()
            _camera().start()
            remote = _jetson().set_preview_source(_remote_source(source))
            return jsonify(_combined(remote, source))

        remote = _jetson().preview_source()
        source = "analog" if remote.get("preview_source") == "analog" else "csi"
        return jsonify(_combined(remote, source))
    except (CameraStreamError, JetsonRecordingError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
