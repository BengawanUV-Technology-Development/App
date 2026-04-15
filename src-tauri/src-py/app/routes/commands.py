from time import time
import uuid, asyncio
from flask import Blueprint, request, jsonify, abort
from app.models import CommandResponse
from app.utils.errors import CommandFailedError, ErrorCode, InvalidRequestError, NotConnectedError
from app.services.command import CommandService

command_bp = Blueprint("command", __name__, url_prefix="/command")
_command_service: CommandService | None = None

def init_command_routes(state_manager, drone):
    global _command_service
    _command_service = CommandService(state_manager, drone)

def _get_service_or_abort():
    if _command_service is None:
        abort(500, description="Command routes not initialized")
    return _command_service

@command_bp.route("/arm", methods=["POST"])
def arm_command():
    service = _get_service_or_abort()
    try:
        result = asyncio.run(service.execute_arm())
        return jsonify(result), 200
    except CommandFailedError as e:
        return _error_response("arm", ErrorCode.COMMAND_FAILED, str(e), 400)
    except Exception as e:
        return _error_response("arm", ErrorCode.INTERNAL_ERROR, str(e), 500)

@command_bp.route("/disarm", methods=["POST"])
def disarm_command():
    service = _get_service_or_abort()

    try:
        result = asyncio.run(service.execute_disarm())
        return jsonify(result), 200
    except NotConnectedError:
        return _error_response("disarm", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")

@command_bp.route("/takeoff", methods=["POST"])
def takeoff_command():
    data = request.get_json(silent=True) or {}
    service = _get_service_or_abort()
    
    try:
        result = asyncio.run(service.execute_takeoff(data.get("altitude_m")))
        return jsonify(result), 200
    except NotConnectedError:
        return _error_response("takeoff", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except InvalidRequestError as e:
        return _error_response("takeoff", ErrorCode.INVALID_REQUEST, str(e))
                

@command_bp.route("/land", methods=["POST"])
def land_command():
    service = _get_service_or_abort()
    
    try:
        result = asyncio.run(service.execute_land())
        return jsonify(result), 200
    except NotConnectedError:
        return _error_response("land", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")

@command_bp.route("/set_takeoff_altitude", methods=["POST"])
def set_takeoff_altitude_command():
    data = request.get_json(silent=True) or {}
    service = _get_service_or_abort()

    try:
        result = asyncio.run(service.execute_set_takeoff_altitude(data.get("altitude_m")))
        return jsonify(result), 200
    except NotConnectedError:
        return _error_response("set_takeoff_altitude", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except InvalidRequestError as e:
        return _error_response("set_takeoff_altitude", ErrorCode.INVALID_REQUEST, str(e))

def _error_response(command_name: str, error_code: ErrorCode, error_message: str, status_code: int = 400):
    resp = CommandResponse(
        ok=False,
        command=command_name,
        command_id=str(uuid.uuid4()),
        ts=time(),
        error_code=error_code.value,
        error=error_message
    )
    return jsonify(resp.to_dict()), status_code
