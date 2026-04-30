from time import time
import asyncio
import logging
import uuid
from typing import Any, cast
from flask import Blueprint, jsonify, request, abort

from app.models import CommandResponse
from app.services.mission import MissionService
from app.utils.session_log import SessionLogStore
from app.utils.errors import (
    CommandFailedError,
    CommandTimeoutError,
    ErrorCode,
    InvalidRequestError,
    NotConnectedError,
)


mission_bp = Blueprint("mission", __name__, url_prefix="/mission")
_mission_service: MissionService | None = None
logger = logging.getLogger(__name__)


def init_mission_routes(state_manager, drone_getter, event_logger: SessionLogStore | None = None):
    global _mission_service
    _mission_service = MissionService(state_manager, drone_getter, event_logger)


def _get_service_or_abort():
    if _mission_service is None:
        abort(500, description="Mission routes not initialized")
    return _mission_service


@mission_bp.route("/upload", methods=["POST"])
def upload_mission_command():
    data = request.get_json(silent=True) or {}
    service = _get_service_or_abort()
    waypoints_raw = data.get("waypoints")

    if not isinstance(waypoints_raw, list):
        raise InvalidRequestError("waypoints must be a list of waypoint objects")

    waypoints = cast(list[dict[str, Any]], waypoints_raw)

    logger.info("mission_request upload waypoints=%s", len(waypoints) if isinstance(waypoints, list) else None)
    try:
        result = asyncio.run(service.execute_upload_mission(waypoints))
        logger.info("mission_response upload ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        return _error_response("mission_upload", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except InvalidRequestError as e:
        return _error_response("mission_upload", ErrorCode.INVALID_REQUEST, str(e))
    except CommandFailedError as e:
        return _error_response("mission_upload", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        return _error_response("mission_upload", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("mission_response upload ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("mission_upload", ErrorCode.INTERNAL_ERROR, str(e), 500)


@mission_bp.route("/start", methods=["POST"])
def start_mission_command():
    service = _get_service_or_abort()

    logger.info("mission_request start")
    try:
        result = asyncio.run(service.execute_start_mission())
        logger.info("mission_response start ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        return _error_response("mission_start", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except CommandFailedError as e:
        return _error_response("mission_start", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        return _error_response("mission_start", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("mission_response start ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("mission_start", ErrorCode.INTERNAL_ERROR, str(e), 500)


@mission_bp.route("/pause", methods=["POST"])
def pause_mission_command():
    service = _get_service_or_abort()

    logger.info("mission_request pause")
    try:
        result = asyncio.run(service.execute_pause_mission())
        logger.info("mission_response pause ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        return _error_response("mission_pause", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except CommandFailedError as e:
        return _error_response("mission_pause", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        return _error_response("mission_pause", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("mission_response pause ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("mission_pause", ErrorCode.INTERNAL_ERROR, str(e), 500)


@mission_bp.route("/clear", methods=["POST"])
def clear_mission_command():
    service = _get_service_or_abort()

    logger.info("mission_request clear")
    try:
        result = asyncio.run(service.execute_clear_mission())
        logger.info("mission_response clear ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        return _error_response("mission_clear", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except CommandFailedError as e:
        return _error_response("mission_clear", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        return _error_response("mission_clear", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("mission_response clear ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("mission_clear", ErrorCode.INTERNAL_ERROR, str(e), 500)


@mission_bp.route("/progress", methods=["GET"])
def mission_progress_command():
    service = _get_service_or_abort()

    logger.info("mission_request progress")
    try:
        result = asyncio.run(service.execute_mission_progress())
        logger.info("mission_response progress ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        return _error_response("mission_progress", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except CommandFailedError as e:
        return _error_response("mission_progress", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        return _error_response("mission_progress", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("mission_response progress ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("mission_progress", ErrorCode.INTERNAL_ERROR, str(e), 500)


def _error_response(command_name: str, error_code: ErrorCode, error_message: str, status_code: int = 400):
    resp = CommandResponse(
        ok=False,
        command=command_name,
        command_id=str(uuid.uuid4()),
        ts=time(),
        error_code=error_code.value,
        error=error_message,
    )
    return jsonify(resp.to_dict()), status_code