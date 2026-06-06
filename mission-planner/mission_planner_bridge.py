"""
BUV Mission Planner HTTP bridge.

Run this file from Mission Planner's Python Script window.
Mission Planner currently embeds IronPython 2.7, so this script intentionally
uses only Python 2.7-compatible syntax and .NET Framework classes.
"""

import json
import threading
import time

try:
    import Queue as queue
except ImportError:
    import queue

try:
    import builtins as bridge_runtime
except ImportError:
    import __builtin__ as bridge_runtime

import clr

clr.AddReference("System")

from System import Array, Byte, DateTime, Guid
from System.Net import IPAddress
from System.Net.Sockets import TcpListener
from System.Text import Encoding


HOST = "127.0.0.1"
PORT = 5000
SNAPSHOT_RATE_HZ = 10.0
COMMAND_TIMEOUT_SECONDS = 5.0
MAX_REQUEST_BYTES = 65536

ALLOWED_FLIGHT_MODES = (
    "MANUAL",
    "FBWA",
    "AUTO",
    "RTL",
    "QSTABILIZE",
    "QHOVER",
    "QLAND",
)

_snapshot_lock = threading.Lock()
_snapshot = {}
_command_queue = queue.Queue()


def _unix_time():
    epoch = DateTime(1970, 1, 1)
    return DateTime.UtcNow.Subtract(epoch).TotalSeconds


def _read_cs(name, default=None):
    try:
        return getattr(cs, name)
    except Exception:
        return default


def _read_number(name, default=None):
    value = _read_cs(name, default)
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return default


def _read_integer(name, default=None):
    value = _read_cs(name, default)
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return default


def _vehicle_connected():
    try:
        return bool(MAV.BaseStream.IsOpen)
    except Exception:
        return bool(_read_cs("lat", 0) or _read_cs("lng", 0))


def _build_snapshot():
    connected = _vehicle_connected()
    return {
        "ok": True,
        "timestamp": _unix_time(),
        "source": "mission-planner",
        "vehicle": {
            "connected": connected,
            "armed": bool(_read_cs("armed", False)),
            "flight_mode": str(_read_cs("mode", "UNKNOWN")),
        },
        "position": {
            "lat": _read_number("lat"),
            "lng": _read_number("lng"),
            "relative_alt_m": _read_number("alt"),
            "absolute_alt_m": None,
            "gps_status": _read_integer("gpsstatus"),
            "gps_hdop": _read_number("gpshdop"),
            "satellites": _read_integer("satcount"),
        },
        "attitude": {
            "roll_deg": _read_number("roll"),
            "pitch_deg": _read_number("pitch"),
            "yaw_deg": _read_number("yaw"),
            "heading_deg": _read_number("yaw"),
            "ground_course_deg": _read_number("groundcourse"),
        },
        "velocity": {
            "airspeed_m_s": _read_number("airspeed"),
            "groundspeed_m_s": _read_number("groundspeed"),
            "vertical_speed_m_s": _read_number("verticalspeed"),
        },
        "battery": {
            "remaining_percent": _read_number("battery_remaining"),
            "voltage_v": _read_number("battery_voltage"),
            "current_a": _read_number("current"),
        },
    }


def _update_snapshot():
    global _snapshot
    next_snapshot = _build_snapshot()
    with _snapshot_lock:
        _snapshot = next_snapshot


def _get_snapshot():
    with _snapshot_lock:
        return dict(_snapshot)


def _health_payload():
    snapshot = _get_snapshot()
    vehicle = snapshot.get("vehicle", {})
    return {
        "ok": True,
        "timestamp": _unix_time(),
        "service": "mission-planner-bridge",
        "vehicle_connected": bool(vehicle.get("connected", False)),
        "snapshot_timestamp": snapshot.get("timestamp"),
    }


def _normalize_mode(mode):
    normalized = str(mode or "").strip().upper().replace("_", "")
    if normalized not in ALLOWED_FLIGHT_MODES:
        raise ValueError("Unsupported flight mode: " + normalized)
    return normalized


def _execute_command(command):
    command_name = command["name"]
    payload = command["payload"]

    if command_name == "set-flight-mode":
        mode = _normalize_mode(payload.get("mode"))
        changed = bool(Script.ChangeMode(mode))
        if not changed:
            raise RuntimeError("Mission Planner rejected flight mode " + mode)
        return {
            "ok": True,
            "request_id": command["request_id"],
            "command": command_name,
            "message": "Flight mode change requested: " + mode,
            "timestamp": _unix_time(),
        }

    if command_name == "arm":
        MAV.doARM(True)
        return {
            "ok": True,
            "request_id": command["request_id"],
            "command": command_name,
            "message": "Arm request sent",
            "timestamp": _unix_time(),
        }

    if command_name == "disarm":
        MAV.doARM(False)
        return {
            "ok": True,
            "request_id": command["request_id"],
            "command": command_name,
            "message": "Disarm request sent",
            "timestamp": _unix_time(),
        }

    if command_name == "reboot":
        if bool(_read_cs("armed", False)):
            raise RuntimeError("Reboot is only allowed while vehicle is disarmed")
        accepted = bool(
            MAV.doCommand(
                MAVLink.MAV_CMD.PREFLIGHT_REBOOT_SHUTDOWN,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        )
        if not accepted:
            raise RuntimeError("Flight controller rejected reboot request")
        return {
            "ok": True,
            "request_id": command["request_id"],
            "command": command_name,
            "message": "Flight controller reboot requested",
            "timestamp": _unix_time(),
        }

    raise ValueError("Unsupported command: " + command_name)


def _process_pending_commands():
    while True:
        try:
            command = _command_queue.get_nowait()
        except queue.Empty:
            return

        try:
            command["result"] = _execute_command(command)
        except Exception as exc:
            command["result"] = {
                "ok": False,
                "request_id": command["request_id"],
                "command": command["name"],
                "error": str(exc),
                "timestamp": _unix_time(),
            }
        finally:
            command["completed"].set()


def _queue_command(name, payload):
    request_id = str(payload.get("request_id") or Guid.NewGuid().ToString())
    command = {
        "name": name,
        "payload": payload,
        "request_id": request_id,
        "completed": threading.Event(),
        "result": None,
    }
    _command_queue.put(command)

    if not command["completed"].wait(COMMAND_TIMEOUT_SECONDS):
        return {
            "ok": False,
            "request_id": request_id,
            "command": name,
            "error": "Mission Planner command timed out",
            "timestamp": _unix_time(),
        }, 504

    result = command["result"]
    return result, 200 if result.get("ok") else 400


def _route_request(method, path, payload):
    if method == "GET" and path == "/api/v1/health":
        return _health_payload(), 200

    if method == "GET" and path == "/api/v1/telemetry":
        return _get_snapshot(), 200

    if method == "POST" and path == "/api/v1/commands/set-flight-mode":
        return _queue_command("set-flight-mode", payload)

    if method == "POST" and path == "/api/v1/commands/arm":
        return _queue_command("arm", payload)

    if method == "POST" and path == "/api/v1/commands/disarm":
        return _queue_command("disarm", payload)

    if method == "POST" and path == "/api/v1/commands/reboot":
        return _queue_command("reboot", payload)

    return {
        "ok": False,
        "error": "Route not found",
        "method": method,
        "path": path,
        "timestamp": _unix_time(),
    }, 404


def _read_request(stream):
    chunks = []
    total_bytes = 0
    header_end = -1
    content_length = 0

    while total_bytes < MAX_REQUEST_BYTES:
        buffer = Array.CreateInstance(Byte, 4096)
        count = stream.Read(buffer, 0, buffer.Length)
        if count <= 0:
            break

        chunk = Encoding.UTF8.GetString(buffer, 0, count)
        chunks.append(chunk)
        total_bytes += count
        text = "".join(chunks)

        if header_end < 0:
            header_end = text.find("\r\n\r\n")
            if header_end >= 0:
                header_text = text[:header_end]
                for line in header_text.split("\r\n")[1:]:
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                        break

        if header_end >= 0 and len(text) >= header_end + 4 + content_length:
            return text

    raise ValueError("Invalid or oversized HTTP request")


def _parse_request(raw_request):
    header_text, body = raw_request.split("\r\n\r\n", 1)
    request_line = header_text.split("\r\n", 1)[0]
    method, target, _http_version = request_line.split(" ", 2)
    path = target.split("?", 1)[0]
    payload = json.loads(body) if body.strip() else {}
    if not isinstance(payload, dict):
        raise ValueError("JSON request body must be an object")
    return method.upper(), path, payload


def _write_response(stream, payload, status_code):
    reason = {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        500: "Internal Server Error",
        504: "Gateway Timeout",
    }.get(status_code, "Error")
    body = json.dumps(payload, separators=(",", ":"))
    response = (
        "HTTP/1.1 {0} {1}\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Content-Length: {2}\r\n"
        "Connection: close\r\n"
        "Access-Control-Allow-Origin: http://127.0.0.1\r\n"
        "\r\n"
        "{3}"
    ).format(status_code, reason, len(Encoding.UTF8.GetBytes(body)), body)
    encoded = Encoding.UTF8.GetBytes(response)
    stream.Write(encoded, 0, encoded.Length)
    stream.Flush()


def _handle_client(client):
    try:
        stream = client.GetStream()
        raw_request = _read_request(stream)
        method, path, payload = _parse_request(raw_request)
        response, status_code = _route_request(method, path, payload)
        _write_response(stream, response, status_code)
    except Exception as exc:
        try:
            _write_response(
                client.GetStream(),
                {"ok": False, "error": str(exc), "timestamp": _unix_time()},
                500,
            )
        except Exception:
            pass
    finally:
        client.Close()


def _stop_previous_server():
    previous_listener = getattr(bridge_runtime, "_buv_bridge_listener", None)
    if previous_listener is None:
        return

    try:
        previous_listener.Stop()
        print("Stopped previous BUV Mission Planner bridge listener")
    except Exception as exc:
        print("Could not stop previous bridge listener: {0}".format(exc))
    finally:
        bridge_runtime._buv_bridge_listener = None


def _server_loop(listener):
    print("BUV Mission Planner bridge listening on http://{0}:{1}".format(HOST, PORT))

    while True:
        try:
            client = listener.AcceptTcpClient()
        except Exception:
            break

        worker = threading.Thread(target=_handle_client, args=(client,))
        worker.daemon = True
        worker.start()

    try:
        listener.Stop()
    except Exception:
        pass


def _start_server():
    _stop_previous_server()

    listener = TcpListener(IPAddress.Loopback, PORT)
    listener.Start()
    bridge_runtime._buv_bridge_listener = listener

    server = threading.Thread(target=_server_loop, args=(listener,))
    server.daemon = True
    server.start()


print("Starting BUV Mission Planner bridge...")
_update_snapshot()
_start_server()

while True:
    _update_snapshot()
    _process_pending_commands()
    Script.Sleep(int(1000.0 / SNAPSHOT_RATE_HZ))
