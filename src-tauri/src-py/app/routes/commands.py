from time import time
import asyncio
import logging
import uuid
from flask import Blueprint, request, jsonify, abort
from app.models import CommandResponse
from app.utils.errors import (
    CommandFailedError,
    CommandTimeoutError,
    ErrorCode,
    InvalidRequestError,
    NotConnectedError,
)
from app.services.command import CommandService
from app.utils.session_log import SessionLogStore

command_bp = Blueprint("command", __name__, url_prefix="/command")
_command_service: CommandService | None = None
_loop_getter = None
_address_updater = None
logger = logging.getLogger(__name__)

def init_command_routes(state_manager, drone_getter, event_logger: SessionLogStore | None = None, loop_getter = None, address_updater = None):
    global _command_service, _loop_getter, _address_updater
    _command_service = CommandService(state_manager, drone_getter, event_logger)
    _loop_getter = loop_getter
    _address_updater = address_updater

@command_bp.route("/connection", methods=["POST"])
def connection_command():
    data = request.get_json(silent=True) or {}
    address = data.get("address")
    if not address:
        return _error_response("connection", ErrorCode.INVALID_REQUEST, "Address is required")

    logger.info("command_request connection address=%s", address)
    if _address_updater:
        changed = _address_updater(address)
        return jsonify({
            "ok": True,
            "command": "connection",
            "message": f"Connection address updated to {address}" if changed else "Address already set",
            "changed": changed
        }), 200
    
    return _error_response("connection", ErrorCode.INTERNAL_ERROR, "Address updater not initialized")

@command_bp.route("/list_ports", methods=["GET"])
def list_ports_command():
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        port_list = []
        for port in ports:
            port_list.append({
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid
            })
        return jsonify({
            "ok": True,
            "ports": port_list
        }), 200
    except Exception as e:
        logger.exception("Failed to list serial ports")
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

def _get_service_or_abort():
    if _command_service is None:
        abort(500, description="Command routes not initialized")
    return _command_service

def _run_sync(coro):
    if _loop_getter is None:
        return asyncio.run(coro)
    
    loop = _loop_getter()
    if loop is None:
        # Fallback if loop not yet captured
        return asyncio.run(coro)
    
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

@command_bp.route("/arm", methods=["POST"])
def arm_command():
    service = _get_service_or_abort()
    logger.info("command_request arm")
    try:
        result = _run_sync(service.execute_arm())
        logger.info("command_response arm ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        logger.info("command_response arm ok=false error_code=%s", ErrorCode.NOT_CONNECTED.value)
        return _error_response("arm", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except CommandFailedError as e:
        logger.warning("command_response arm ok=false error_code=%s error=%s", ErrorCode.COMMAND_FAILED.value, e)
        return _error_response("arm", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        logger.warning("command_response arm ok=false error_code=%s error=%s", ErrorCode.TIMEOUT.value, e)
        return _error_response("arm", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("command_response arm ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("arm", ErrorCode.INTERNAL_ERROR, str(e), 500)

@command_bp.route("/disarm", methods=["POST"])
def disarm_command():
    service = _get_service_or_abort()

    logger.info("command_request disarm")
    try:
        result = _run_sync(service.execute_disarm())
        logger.info("command_response disarm ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        logger.info("command_response disarm ok=false error_code=%s", ErrorCode.NOT_CONNECTED.value)
        return _error_response("disarm", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except CommandFailedError as e:
        logger.warning("command_response disarm ok=false error_code=%s error=%s", ErrorCode.COMMAND_FAILED.value, e)
        return _error_response("disarm", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        logger.warning("command_response disarm ok=false error_code=%s error=%s", ErrorCode.TIMEOUT.value, e)
        return _error_response("disarm", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("command_response disarm ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("disarm", ErrorCode.INTERNAL_ERROR, str(e), 500)

@command_bp.route("/takeoff", methods=["POST"])
def takeoff_command():
    data = request.get_json(silent=True) or {}
    service = _get_service_or_abort()
    logger.info("command_request takeoff altitude_m=%s", data.get("altitude_m"))
    try:
        result = _run_sync(service.execute_takeoff(data.get("altitude_m")))
        logger.info("command_response takeoff ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        logger.info("command_response takeoff ok=false error_code=%s", ErrorCode.NOT_CONNECTED.value)
        return _error_response("takeoff", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except InvalidRequestError as e:
        logger.info("command_response takeoff ok=false error_code=%s error=%s", ErrorCode.INVALID_REQUEST.value, e)
        return _error_response("takeoff", ErrorCode.INVALID_REQUEST, str(e))
    except CommandFailedError as e:
        logger.warning("command_response takeoff ok=false error_code=%s error=%s", ErrorCode.COMMAND_FAILED.value, e)
        return _error_response("takeoff", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        logger.warning("command_response takeoff ok=false error_code=%s error=%s", ErrorCode.TIMEOUT.value, e)
        return _error_response("takeoff", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("command_response takeoff ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("takeoff", ErrorCode.INTERNAL_ERROR, str(e), 500)

@command_bp.route("/land", methods=["POST"])
def land_command():
    service = _get_service_or_abort()

    logger.info("command_request land")
    try:
        result = _run_sync(service.execute_land())
        logger.info("command_response land ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        logger.info("command_response land ok=false error_code=%s", ErrorCode.NOT_CONNECTED.value)
        return _error_response("land", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except CommandFailedError as e:
        logger.warning("command_response land ok=false error_code=%s error=%s", ErrorCode.COMMAND_FAILED.value, e)
        return _error_response("land", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        logger.warning("command_response land ok=false error_code=%s error=%s", ErrorCode.TIMEOUT.value, e)
        return _error_response("land", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("command_response land ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("land", ErrorCode.INTERNAL_ERROR, str(e), 500)

@command_bp.route("/set_takeoff_altitude", methods=["POST"])
def set_takeoff_altitude_command():
    data = request.get_json(silent=True) or {}
    service = _get_service_or_abort()

    logger.info("command_request set_takeoff_altitude altitude_m=%s", data.get("altitude_m"))
    try:
        result = _run_sync(service.execute_set_takeoff_altitude(data.get("altitude_m")))
        logger.info("command_response set_takeoff_altitude ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        logger.info("command_response set_takeoff_altitude ok=false error_code=%s", ErrorCode.NOT_CONNECTED.value)
        return _error_response("set_takeoff_altitude", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except InvalidRequestError as e:
        logger.info("command_response set_takeoff_altitude ok=false error_code=%s error=%s", ErrorCode.INVALID_REQUEST.value, e)
        return _error_response("set_takeoff_altitude", ErrorCode.INVALID_REQUEST, str(e))
    except CommandFailedError as e:
        logger.warning("command_response set_takeoff_altitude ok=false error_code=%s error=%s", ErrorCode.COMMAND_FAILED.value, e)
        return _error_response("set_takeoff_altitude", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        logger.warning("command_response set_takeoff_altitude ok=false error_code=%s error=%s", ErrorCode.TIMEOUT.value, e)
        return _error_response("set_takeoff_altitude", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("command_response set_takeoff_altitude ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("set_takeoff_altitude", ErrorCode.INTERNAL_ERROR, str(e), 500)

@command_bp.route("/set_flight_mode", methods=["POST"])
def set_flight_mode_command():
    data = request.get_json(silent=True) or {}
    service = _get_service_or_abort()

    logger.info("command_request set_flight_mode mode=%s", data.get("mode"))
    try:
        result = _run_sync(service.execute_set_flight_mode(data.get("mode")))
        logger.info("command_response set_flight_mode ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        logger.info("command_response set_flight_mode ok=false error_code=%s", ErrorCode.NOT_CONNECTED.value)
        return _error_response("set_flight_mode", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except InvalidRequestError as e:
        logger.info("command_response set_flight_mode ok=false error_code=%s error=%s", ErrorCode.INVALID_REQUEST.value, e)
        return _error_response("set_flight_mode", ErrorCode.INVALID_REQUEST, str(e))
    except CommandFailedError as e:
        logger.warning("command_response set_flight_mode ok=false error_code=%s error=%s", ErrorCode.COMMAND_FAILED.value, e)
        return _error_response("set_flight_mode", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        logger.warning("command_response set_flight_mode ok=false error_code=%s error=%s", ErrorCode.TIMEOUT.value, e)
        return _error_response("set_flight_mode", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("command_response set_flight_mode ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("set_flight_mode", ErrorCode.INTERNAL_ERROR, str(e), 500)

@command_bp.route("/reboot", methods=["POST"])
def reboot_command():
    service = _get_service_or_abort()

    logger.info("command_request reboot")
    try:
        result = _run_sync(service.execute_reboot())
        logger.info("command_response reboot ok=true command_id=%s", result.get("command_id"))
        return jsonify(result), 200
    except NotConnectedError:
        logger.info("command_response reboot ok=false error_code=%s", ErrorCode.NOT_CONNECTED.value)
        return _error_response("reboot", ErrorCode.NOT_CONNECTED, "Vehicle is not connected")
    except InvalidRequestError as e:
        logger.info("command_response reboot ok=false error_code=%s error=%s", ErrorCode.INVALID_REQUEST.value, e)
        return _error_response("reboot", ErrorCode.INVALID_REQUEST, str(e))
    except CommandFailedError as e:
        logger.warning("command_response reboot ok=false error_code=%s error=%s", ErrorCode.COMMAND_FAILED.value, e)
        return _error_response("reboot", ErrorCode.COMMAND_FAILED, str(e), 400)
    except CommandTimeoutError as e:
        logger.warning("command_response reboot ok=false error_code=%s error=%s", ErrorCode.TIMEOUT.value, e)
        return _error_response("reboot", ErrorCode.TIMEOUT, str(e), 504)
    except Exception as e:
        logger.exception("command_response reboot ok=false error_code=%s", ErrorCode.INTERNAL_ERROR.value)
        return _error_response("reboot", ErrorCode.INTERNAL_ERROR, str(e), 500)

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
