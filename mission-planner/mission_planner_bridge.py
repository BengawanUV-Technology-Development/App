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

try:
    basestring
except NameError:
    basestring = str

import clr

clr.AddReference("System")
clr.AddReference("MAVLink")

import MAVLink

from System import Array, Byte, DateTime, Guid
from System.Net import IPAddress
from System.Net.Sockets import TcpListener
from System.Text import Encoding


HOST = "127.0.0.1"
PORT = 5000
BRIDGE_VERSION = "1.5.1"
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
MAV_CMD_NAMES = {
    16: "WAYPOINT",
    17: "LOITER_UNLIM",
    18: "LOITER_TURNS",
    19: "LOITER_TIME",
    20: "RTL",
    21: "LAND",
    22: "TAKEOFF",
    84: "VTOL_TAKEOFF",
    85: "VTOL_LAND",
    177: "DO_JUMP",
}

_snapshot_lock = threading.Lock()
_snapshot = {}
_command_queue = queue.Queue()
_state_source = "cs"

MISSION_CACHE_TTL_SECONDS = 5.0
_mission_cache_lock = threading.Lock()
_mission_cache = None
_mission_cache_at = 0.0


def _unix_time():
    epoch = DateTime(1970, 1, 1)
    return DateTime.UtcNow.Subtract(epoch).TotalSeconds


def _read_state(state, name, default=None):
    try:
        return getattr(state, name)
    except Exception:
        return default


def _state_candidates():
    candidates = []

    try:
        candidates.append(("cs", cs))
    except Exception:
        pass

    try:
        candidates.append(("MAV.cs", MAV.cs))
    except Exception:
        pass

    try:
        candidates.append(("MAV.MAV.cs", MAV.MAV.cs))
    except Exception:
        pass

    return candidates


def _state_score(state):
    score = 0
    mode = str(_read_state(state, "mode", "UNKNOWN")).strip().upper()
    if mode not in ("", "UNKNOWN", "NONE"):
        score += 10
    if bool(_read_state(state, "armed", False)):
        score += 8
    if int(_read_state(state, "satcount", 0) or 0) > 0:
        score += 5
    if int(_read_state(state, "gpsstatus", 0) or 0) >= 3:
        score += 5
    if float(_read_state(state, "battery_voltage", 0) or 0) > 0:
        score += 3
    if float(_read_state(state, "lat", 0) or 0) != 0 or float(_read_state(state, "lng", 0) or 0) != 0:
        score += 3
    return score


def _active_state():
    global _state_source
    candidates = _state_candidates()
    if not candidates:
        raise RuntimeError("Mission Planner CurrentState is unavailable")
    _state_source, state = max(candidates, key=lambda item: _state_score(item[1]))
    return state


def _read_cs(name, default=None):
    return _read_state(_active_state(), name, default)


def _read_number(state, name, default=None):
    value = _read_state(state, name, default)
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return default


def _read_integer(state, name, default=None):
    value = _read_state(state, name, default)
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return default


def _first_integer(obj, names, default=None):
    for name in names:
        value = _read_integer(obj, name, None)
        if value is not None:
            return value
    return default


def _vehicle_connected():
    try:
        return bool(MAV.BaseStream.IsOpen)
    except Exception:
        return bool(_read_cs("lat", 0) or _read_cs("lng", 0))


def _build_snapshot():
    state = _active_state()
    connected = _vehicle_connected()
    return {
        "ok": True,
        "timestamp": _unix_time(),
        "source": "mission-planner",
        "vehicle": {
            "connected": connected,
            "armed": bool(_read_state(state, "armed", False)),
            "flight_mode": str(_read_state(state, "mode", "UNKNOWN")),
        },
        "position": {
            "lat": _read_number(state, "lat"),
            "lng": _read_number(state, "lng"),
            "relative_alt_m": _read_number(state, "alt"),
            "absolute_alt_m": None,
            "gps_status": _read_integer(state, "gpsstatus"),
            "gps_hdop": _read_number(state, "gpshdop"),
            "satellites": _read_integer(state, "satcount"),
        },
        "attitude": {
            "roll_deg": _read_number(state, "roll"),
            "pitch_deg": _read_number(state, "pitch"),
            "yaw_deg": _read_number(state, "yaw"),
            "heading_deg": _read_number(state, "yaw"),
            "ground_course_deg": _read_number(state, "groundcourse"),
        },
        "velocity": {
            "airspeed_m_s": _read_number(state, "airspeed"),
            "groundspeed_m_s": _read_number(state, "groundspeed"),
            "vertical_speed_m_s": _read_number(state, "verticalspeed"),
        },
        "battery": {
            "remaining_percent": _read_number(state, "battery_remaining"),
            "voltage_v": _read_number(state, "battery_voltage"),
            "current_a": _read_number(state, "current"),
        },
        "ekf": {
            "ok": bool(_read_state(state, "ekf_ok", True)),
            "flags": _read_integer(state, "ekfstatus"),
            "velocity_variance": _read_number(state, "vw"),
            "pos_variance": _read_number(state, "pe"),
            "compass_variance": _read_number(state, "me"),
        },
        "vibration": {
            "x": _read_number(state, "vibex"),
            "y": _read_number(state, "vibey"),
            "z": _read_number(state, "vibez"),
        },
        "status": {
            "dist_to_home_m": _read_number(state, "distToHome"),
            "time_in_air_s": _read_number(state, "timeInAir"),
            "time_since_boot_s": (_read_number(state, "time_boot_ms") or 0) / 1000.0,
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
        "version": BRIDGE_VERSION,
        "capabilities": ["telemetry", "mission", "messages", "arm", "disarm", "set-flight-mode", "set-current-waypoint", "reboot", "diagnostics"],
        "vehicle_connected": bool(vehicle.get("connected", False)),
        "snapshot_timestamp": snapshot.get("timestamp"),
        "state_source": _state_source,
    }


def _diagnostics_payload():
    candidates = []
    for name, state in _state_candidates():
        candidates.append({
            "name": name,
            "score": _state_score(state),
            "armed": bool(_read_state(state, "armed", False)),
            "mode": str(_read_state(state, "mode", "UNKNOWN")),
            "lat": _read_number(state, "lat"),
            "lng": _read_number(state, "lng"),
            "satellites": _read_integer(state, "satcount"),
            "battery_voltage_v": _read_number(state, "battery_voltage"),
        })
    return {
        "ok": True,
        "timestamp": _unix_time(),
        "selected_state_source": _state_source,
        "candidates": candidates,
    }


def _enum_name(value):
    if value in MAV_CMD_NAMES:
        return MAV_CMD_NAMES[value]
    try:
        return str(value).split(".")[-1]
    except Exception:
        return str(value)


def _timestamp_from_value(value):
    if value is None:
        return None
    try:
        # .NET DateTime
        return value.ToUniversalTime().Subtract(DateTime(1970, 1, 1)).TotalSeconds
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def _append_message(items, timestamp, text, source_name):
    message = str(text or "").strip()
    if not message:
        return
    items.append({
        "timestamp": timestamp,
        "message": message,
        "source": source_name,
    })


def _read_message_collection(collection, source_name):
    items = []
    if collection is None:
        return items
    if isinstance(collection, basestring):
        _append_message(items, None, collection, source_name)
        return items

    try:
        keys = list(collection.Keys)
        for key in keys:
            try:
                _append_message(items, _timestamp_from_value(key), collection[key], source_name)
            except Exception:
                pass
        return items
    except Exception:
        pass

    try:
        for item in collection:
            timestamp = None
            message = None
            # Mission Planner stores CurrentState.messages as tuples where
            # Item1 is DateTime and Item2 is the displayed message text.
            try:
                timestamp = _timestamp_from_value(getattr(item, "Item1"))
                message = getattr(item, "Item2")
            except Exception:
                pass
            try:
                if timestamp is None:
                    timestamp = _timestamp_from_value(getattr(item, "time"))
            except Exception:
                pass
            try:
                if message is None:
                    message = getattr(item, "message")
            except Exception:
                pass
            if message is None:
                message = item
            _append_message(items, timestamp, message, source_name)
    except Exception:
        pass
    return items


def _messages_payload():
    items = []
    sources_checked = []
    for source_name, source in _state_candidates() + [("MAV", MAV)]:
        for property_name in ("messages", "Messages", "message", "Message"):
            sources_checked.append(source_name + "." + property_name)
            try:
                collection = getattr(source, property_name)
            except Exception:
                continue
            items.extend(_read_message_collection(collection, source_name + "." + property_name))

    deduped = []
    seen = set()
    for item in items:
        key = (item.get("timestamp"), item.get("message"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    deduped.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    return {
        "ok": True,
        "timestamp": _unix_time(),
        "source": "mission-planner",
        "count": len(deduped[:80]),
        "messages": deduped[:80],
        "sources_checked": sources_checked,
    }


def _mission_payload():
    global _mission_cache, _mission_cache_at

    now = time.time()
    with _mission_cache_lock:
        if (
            _mission_cache is not None
            and (now - _mission_cache_at) < MISSION_CACHE_TTL_SECONDS
        ):
            cached = dict(_mission_cache)
            cached["cached"] = True
            cached["cache_age_seconds"] = now - _mission_cache_at
            return cached

    waypoints = []
    current_seq = None
    try:
        count = int(MAV.getWPCount())
    except Exception as exc:
        return {
            "ok": False,
            "timestamp": _unix_time(),
            "error": "Mission Planner waypoint list unavailable: " + str(exc),
            "count": 0,
            "waypoints": [],
        }

    try:
        current_seq = _first_integer(
            _active_state(),
            ("wpno", "wp", "missioncurrent", "mission_current", "currentwp", "current_wp"),
        )
    except Exception:
        current_seq = None

    if current_seq is None:
        current_seq = _first_integer(MAV, ("wpno", "wps_current", "currentwp", "current_wp"))

    for index in range(max(0, count)):
        try:
            waypoint = MAV.getWP(index)
            command_id = _read_integer(waypoint, "id")
            frame_id = _read_integer(waypoint, "frame")
            waypoints.append({
                "index": index,
                "seq": index,
                "command": command_id,
                "command_name": _enum_name(command_id),
                "frame": frame_id,
                "lat": _read_number(waypoint, "lat"),
                "lng": _read_number(waypoint, "lng"),
                "alt_m": _read_number(waypoint, "alt"),
                "param1": _read_number(waypoint, "p1"),
                "param2": _read_number(waypoint, "p2"),
                "param3": _read_number(waypoint, "p3"),
                "param4": _read_number(waypoint, "p4"),
            })
        except Exception as exc:
            waypoints.append({
                "index": index,
                "seq": index,
                "error": str(exc),
            })

    payload = {
        "ok": True,
        "timestamp": _unix_time(),
        "source": "mission-planner",
        "count": len(waypoints),
        "current_seq": current_seq,
        "waypoints": waypoints,
        "cached": False,
        "cache_age_seconds": 0.0,
    }
    with _mission_cache_lock:
        _mission_cache = payload
        _mission_cache_at = now
    return dict(payload)


def _normalize_mode(mode):
    normalized = str(mode or "").strip().upper().replace("_", "")
    if normalized not in ALLOWED_FLIGHT_MODES:
        raise ValueError("Unsupported flight mode: " + normalized)
    return normalized


def _mission_count():
    try:
        return int(MAV.getWPCount())
    except Exception:
        return 0


def _set_current_waypoint(seq):
    count = _mission_count()
    if count <= 0:
        raise RuntimeError("Mission Planner has no loaded mission")
    if seq < 0 or seq >= count:
        raise ValueError("Waypoint index {0} is outside mission range 0..{1}".format(seq, count - 1))

    helper_names = ("setWPCurrent", "setWPCur", "setWPCurrentIndex", "setCurrentWP")
    attempted = []
    for helper_name in helper_names:
        helper = getattr(MAV, helper_name, None)
        if helper is None:
            continue
        attempted.append(helper_name)
        try:
            result = helper(seq)
            if result is False:
                raise RuntimeError(helper_name + " returned False")
            return helper_name
        except Exception as exc:
            attempted.append(helper_name + ": " + str(exc))

    raise RuntimeError(
        "Mission Planner waypoint-current helper is unavailable. Tried: "
        + (", ".join(attempted) if attempted else ", ".join(helper_names))
    )


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
        # Use Mission Planner's native helper so it can manage the temporary
        # link loss and reconnect behavior around a normal autopilot reboot.
        MAV.doReboot(False)
        return {
            "ok": True,
            "request_id": command["request_id"],
            "command": command_name,
            "message": "Flight controller reboot requested; telemetry will disconnect temporarily",
            "timestamp": _unix_time(),
        }

    if command_name == "set-current-waypoint":
        try:
            seq = int(payload.get("seq"))
        except Exception:
            raise ValueError("seq is required and must be an integer")
        helper_name = _set_current_waypoint(seq)
        return {
            "ok": True,
            "request_id": command["request_id"],
            "command": command_name,
            "seq": seq,
            "message": "Current mission waypoint requested: WP {0} via {1}".format(seq, helper_name),
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
            command["started"].set()
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
        "started": threading.Event(),
        "completed": threading.Event(),
        "result": None,
    }
    _command_queue.put(command)

    if name == "reboot":
        if not command["started"].wait(COMMAND_TIMEOUT_SECONDS):
            return {
                "ok": False,
                "request_id": request_id,
                "command": name,
                "error": "Mission Planner command did not start",
                "timestamp": _unix_time(),
            }, 504
        return {
            "ok": True,
            "accepted": True,
            "request_id": request_id,
            "command": name,
            "message": "Flight controller reboot started; waiting for Mission Planner to reconnect",
            "timestamp": _unix_time(),
        }, 202

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

    if method == "GET" and path == "/api/v1/diagnostics":
        return _diagnostics_payload(), 200

    if method == "GET" and path == "/api/v1/mission":
        mission = _mission_payload()
        return mission, 200 if mission.get("ok") else 503

    if method == "GET" and path == "/api/v1/messages":
        return _messages_payload(), 200

    if method == "POST" and path == "/api/v1/commands/set-flight-mode":
        return _queue_command("set-flight-mode", payload)

    if method == "POST" and path == "/api/v1/commands/arm":
        return _queue_command("arm", payload)

    if method == "POST" and path == "/api/v1/commands/disarm":
        return _queue_command("disarm", payload)

    if method == "POST" and path == "/api/v1/commands/reboot":
        return _queue_command("reboot", payload)

    if method == "POST" and path == "/api/v1/commands/set-current-waypoint":
        return _queue_command("set-current-waypoint", payload)

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
        202: "Accepted",
        400: "Bad Request",
        404: "Not Found",
        500: "Internal Server Error",
        503: "Service Unavailable",
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

    listener = TcpListener(IPAddress.Any, PORT)
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
