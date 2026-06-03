import re
import sys
import time
from flask import Blueprint, jsonify, request
from serial.tools import list_ports

from app.utils.state import StateManager

connection_bp = Blueprint("connection", __name__, url_prefix="/connection")
_state_manager: StateManager | None = None
_connect_callback = None
_disconnect_callback = None

SUPPORTED_BAUDS = [57600, 115200, 230400, 460800, 921600]
NETWORK_PORTS = ["TCP", "UDP", "UDPCI", "WS"]


def init_connection_routes(state_manager: StateManager, connect_callback, disconnect_callback):
    global _state_manager, _connect_callback, _disconnect_callback
    _state_manager = state_manager
    _connect_callback = connect_callback
    _disconnect_callback = disconnect_callback


def _normalize_serial_address(port: str, baud: int) -> str:
    clean_port = str(port or "").strip()
    upper_port = clean_port.upper()
    if upper_port == "AUTO":
        raise ValueError("AUTO did not find a detected flight controller port")
    if upper_port == "TCP":
        return "tcp://127.0.0.1:5760"
    if upper_port == "UDP":
        return "udp://:14550"
    if upper_port == "UDPCI":
        return "udp://:14540"
    if upper_port == "WS":
        raise ValueError("WebSocket transport is not supported by MAVSDK in this backend")
    if not re.match(r"^(COM\d+|/dev/[\w./-]+)$", clean_port, re.IGNORECASE):
        raise ValueError("Invalid serial port")
    if int(baud) not in SUPPORTED_BAUDS:
        raise ValueError("Unsupported baud rate")
    return f"serial://{clean_port}:{int(baud)}"


def _serial_candidates(detected_ports: list[dict]) -> list[str]:
    detected = [port["device"] for port in detected_ports]
    if sys.platform.startswith("win"):
        common = [f"COM{number}" for number in range(1, 31)]
    else:
        common = [
            "/dev/ttyUSB0",
            "/dev/ttyUSB1",
            "/dev/ttyACM0",
            "/dev/ttyACM1",
            "/dev/serial0",
        ]

    candidates = []
    for item in ["AUTO", *detected, *common, *NETWORK_PORTS]:
        if item not in candidates:
            candidates.append(item)
    return candidates


@connection_bp.route("/ports", methods=["GET"])
def list_serial_ports():
    ports = [
        {
            "device": item.device,
            "name": item.name,
            "description": item.description,
            "hwid": item.hwid,
            "label": f"{item.device} {item.description}".strip(),
        }
        for item in list_ports.comports()
    ]
    print(
        "[connection] scanned ports: "
        + (", ".join(f"{port['device']}={port['description']}" for port in ports) if ports else "none"),
        flush=True,
    )
    return jsonify({"ok": True, "ports": ports, "candidates": _serial_candidates(ports), "bauds": SUPPORTED_BAUDS})


@connection_bp.route("/connect", methods=["POST"])
def connect_vehicle():
    if _state_manager is None or _connect_callback is None:
        return jsonify({"ok": False, "error": "Connection manager not initialized"}), 500

    payload = request.get_json(silent=True) or {}
    try:
        if payload.get("system_address"):
            system_address = str(payload["system_address"]).strip()
        else:
            system_address = _normalize_serial_address(payload.get("port"), int(payload.get("baud", 115200)))
        if not system_address:
            raise ValueError("Select a serial port first")
    except (TypeError, ValueError) as exc:
        print(f"[connection] connect rejected: payload={payload} error={exc}", flush=True)
        return jsonify({"ok": False, "error": str(exc)}), 400

    print(f"[connection] connect requested: target={system_address}", flush=True)
    result = _connect_callback(system_address)
    _state_manager.update(
        connected=False,
        status="CONNECTING",
        error=None,
        system_address=system_address,
        last_update=time.time(),
    )
    return jsonify({"ok": True, "system_address": system_address, **result})


@connection_bp.route("/disconnect", methods=["POST"])
def disconnect_vehicle():
    if _state_manager is None or _disconnect_callback is None:
        return jsonify({"ok": False, "error": "Connection manager not initialized"}), 500

    print("[connection] disconnect requested", flush=True)
    result = _disconnect_callback()
    _state_manager.update(connected=False, status="DISCONNECTED", error=None, last_update=time.time())
    return jsonify({"ok": True, **result})
