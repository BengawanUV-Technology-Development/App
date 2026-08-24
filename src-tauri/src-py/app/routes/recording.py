"""Camera-source and Jetson recording controls."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.config import API_PORT
from app.services.camera_stream import CameraStreamError, CameraStreamService
from app.services.jetson_recording import JetsonRecordingClient, JetsonRecordingError


recording_bp = Blueprint("recording", __name__, url_prefix="/api/v1")
_camera_service: CameraStreamService | None = None
_jetson_client: JetsonRecordingClient | None = None


def init_recording_routes(
    camera_service: CameraStreamService,
    jetson_client: JetsonRecordingClient,
) -> None:
    global _camera_service, _jetson_client
    _camera_service = camera_service
    _jetson_client = jetson_client


def _camera() -> CameraStreamService:
    if _camera_service is None:
        raise RuntimeError("Camera service is not initialized")
    return _camera_service


def _jetson() -> JetsonRecordingClient:
    if _jetson_client is None:
        raise RuntimeError("Jetson recording client is not initialized")
    return _jetson_client


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
    return result


@recording_bp.route("/recordings/status", methods=["GET"])
def recording_status():
    try:
        remote = _jetson().status()
        return jsonify(_combined(remote))
    except JetsonRecordingError as exc:
        return jsonify({"ok": False, "status": "REMOTE_UNKNOWN", "recording": False, "error": str(exc)}), 503


@recording_bp.route("/recordings/start", methods=["POST"])
def recording_start():
    source = "csi"
    camera_started = False
    try:
        source = _source_from_request()
        camera = _camera()
        camera.start()
        camera_started = True
        remote = _jetson().start(
            label=f"web-{source}",
            video_port=camera.port,
            api_port=API_PORT,
        )
        if source == "analog":
            remote = _jetson().set_preview_source("analog")
        return jsonify(_combined(remote, source)), 202
    except (CameraStreamError, JetsonRecordingError) as exc:
        if camera_started:
            try:
                _camera().stop()
            except CameraStreamError:
                pass
        return jsonify({"ok": False, "status": "FAILED", "recording": False, "source": source, "error": str(exc)}), 503


@recording_bp.route("/recordings/stop", methods=["POST"])
def recording_stop():
    try:
        remote = _jetson().stop()
        camera = _camera()
        camera.stop()
        return jsonify(_combined(remote))
    except (CameraStreamError, JetsonRecordingError) as exc:
        return jsonify({"ok": False, "status": "FAILED", "recording": False, "error": str(exc)}), 409


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
