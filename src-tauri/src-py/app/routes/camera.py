"""HTTP endpoints for the receive-only Jetson camera preview."""

from flask import Blueprint, Response, jsonify

from app.services.camera_stream import CameraStreamError, CameraStreamService


camera_bp = Blueprint("camera", __name__, url_prefix="/api/v1")
_camera_service: CameraStreamService | None = None


def init_camera_routes(camera_service: CameraStreamService) -> None:
    global _camera_service
    _camera_service = camera_service


def _get_camera_service() -> CameraStreamService:
    if _camera_service is None:
        raise RuntimeError("Camera service is not initialized")
    return _camera_service


@camera_bp.route("/camera/status", methods=["GET"])
def camera_status():
    return jsonify({"ok": True, **_get_camera_service().status()})


@camera_bp.route("/camera/start", methods=["POST"])
def camera_start():
    try:
        return jsonify({"ok": True, **_get_camera_service().start()}), 202
    except CameraStreamError as exc:
        return jsonify({"ok": False, **_get_camera_service().status(), "error": str(exc)}), 503


@camera_bp.route("/camera/stop", methods=["POST"])
def camera_stop():
    try:
        return jsonify({"ok": True, **_get_camera_service().stop()})
    except CameraStreamError as exc:
        return jsonify({"ok": False, **_get_camera_service().status(), "error": str(exc)}), 409


@camera_bp.route("/camera/preview", methods=["GET"])
def camera_preview():
    service = _get_camera_service()
    try:
        # Start before constructing the response so missing GStreamer
        # dependencies produce a useful JSON error instead of a broken stream
        # after Flask has already sent HTTP headers.
        service.start()
    except CameraStreamError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503

    return Response(
        service.preview_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "X-Accel-Buffering": "no",
        },
    )
