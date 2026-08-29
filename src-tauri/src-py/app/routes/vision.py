"""Authenticated Jetson detection ingestion and safe live-target readout."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.vision_ingest import (
    VisionDetectionService,
    VisionIngestError,
    is_bearer_token_valid,
)


vision_bp = Blueprint("vision", __name__, url_prefix="/api/v1/detection")
_service: VisionDetectionService | None = None
_ingest_token = ""
_read_token = ""


def init_vision_routes(
    service: VisionDetectionService,
    ingest_token: str = "",
    read_token: str = "",
) -> None:
    global _service, _ingest_token, _read_token
    _service = service
    _ingest_token = ingest_token.strip()
    _read_token = read_token.strip() or _ingest_token


def _get_service() -> VisionDetectionService:
    if _service is None:
        raise RuntimeError("Vision detection service is not initialized")
    return _service


def _authorized() -> bool:
    return is_bearer_token_valid(request.headers.get("Authorization"), _ingest_token)


def _auth_error():
    if not _ingest_token:
        return jsonify({
            "ok": False,
            "error_code": "VISION_INGEST_NOT_CONFIGURED",
            "error": "vision ingest token is not configured",
        }), 503
    return jsonify({
        "ok": False,
        "error_code": "UNAUTHORIZED",
        "error": "valid Bearer token is required",
    }), 401


def _read_authorized() -> bool:
    # The desktop UI talks to the local backend over loopback. Any non-local
    # read must carry a token once the API is exposed on Tailscale.
    remote_addr = request.remote_addr or ""
    if remote_addr in {"127.0.0.1", "::1"} or remote_addr.startswith("::ffff:127."):
        return True
    return is_bearer_token_valid(request.headers.get("Authorization"), _read_token)


def _payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise VisionIngestError("request body must be a JSON object", code="JSON_OBJECT_REQUIRED")
    return payload


@vision_bp.route("/ingest", methods=["POST"])
def ingest_detection():
    if not _authorized():
        return _auth_error()
    try:
        detection = _get_service().ingest_event(_payload())
    except VisionIngestError as exc:
        status = 409 if exc.code in {"MISSION_NOT_ACTIVE", "MISSION_ALREADY_ACTIVE", "MISSION_MISMATCH"} else 400
        return jsonify({"ok": False, "error_code": exc.code, "error": str(exc)}), status
    return jsonify({"ok": True, "accepted": True, "detection": detection}), 202


@vision_bp.route("/overlay", methods=["POST"])
def ingest_overlay():
    if not _authorized():
        return _auth_error()
    try:
        result = _get_service().ingest_overlay(_payload())
    except VisionIngestError as exc:
        status = 409 if exc.code in {"MISSION_NOT_ACTIVE", "MISSION_MISMATCH"} else 400
        return jsonify({"ok": False, "error_code": exc.code, "error": str(exc)}), status
    return jsonify({"ok": True, **result}), 202


@vision_bp.route("/latest", methods=["GET"])
def latest_detection():
    if not _read_authorized():
        return _auth_error()
    return jsonify(_get_service().latest())


@vision_bp.route("/status", methods=["GET"])
def detection_status():
    if not _read_authorized():
        return _auth_error()
    return jsonify({"ok": True, **_get_service().status()})


@vision_bp.route("/overlay", methods=["GET"])
def latest_overlay():
    if not _read_authorized():
        return _auth_error()
    latest = _get_service().latest()
    return jsonify({
        "ok": True,
        "active": latest["active"],
        "mission_id": latest["mission_id"],
        "overlay": latest["latest_overlay"],
    })
