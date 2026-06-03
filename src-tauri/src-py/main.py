# src-tauri/src-py/main.py
import asyncio
import logging
import os
import time
import random
import math
import socket
import threading
import json
from flask import Flask, jsonify, request
from flask_cors import CORS
from mavsdk import System
from app.routes.connection import connection_bp, init_connection_routes
from app.routes.mission import mission_bp, init_mission_routes
from app.routes.logs import logs_bp, init_log_routes
from app.routes.telemetry import telemetry_bp, init_telemetry_routes
from app.routes.health import health_bp, init_health_routes
from app.routes.commands import command_bp, init_command_routes
from app.services.command import ARDUPILOT_MODE_REVERSE_MAPPING
from app.utils.state import StateManager
from app.utils.session_log import SessionLogStore

MAVSDK_ADDRESS = os.getenv("MAVSDK_ADDRESS", "")
MAVSDK_SERVER_PORT = int(os.getenv("MAVSDK_SERVER_PORT", "0"))
AUTO_CONNECT = os.getenv("AUTO_CONNECT", "0").strip().lower() in {"1", "true", "yes"}
API_PORT = int(os.getenv("API_PORT", "5001"))
CONNECT_TIMEOUT_SECONDS = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "8"))
CONNECT_CALL_TIMEOUT_SECONDS = float(os.getenv("CONNECT_CALL_TIMEOUT_SECONDS", "15"))
RETRY_DELAY_SECONDS = float(os.getenv("RETRY_DELAY_SECONDS", "5"))
SERIAL_ACCESS_DENIED_RETRY_DELAY_SECONDS = float(
    os.getenv("SERIAL_ACCESS_DENIED_RETRY_DELAY_SECONDS", "10")
)


app = Flask(__name__)
CORS(app)


@app.before_request
def _log_http_request():
    if request.path in {"/health", "/telemetry"}:
        return
    payload = request.get_json(silent=True) if request.method in {"POST", "PUT", "PATCH"} else None
    print(f"[http] -> {request.method} {request.path} payload={payload or '-'}", flush=True)


@app.after_request
def _log_http_response(response):
    if request.path not in {"/health", "/telemetry"}:
        print(f"[http] <- {request.method} {request.path} status={response.status_code}", flush=True)
    return response


def _print_startup_banner():
    route_list = ", ".join(sorted(rule.rule for rule in app.url_map.iter_rules()))
    print("=" * 72, flush=True)
    print(f"[startup] backend pid={os.getpid()} cwd={os.getcwd()}", flush=True)
    print(f"[startup] api=http://127.0.0.1:{API_PORT} auto_connect={AUTO_CONNECT}", flush=True)
    print(f"[startup] default MAVSDK_ADDRESS={MAVSDK_ADDRESS or '-'} server_port={MAVSDK_SERVER_PORT or 'auto'}", flush=True)
    print("[startup] command and connection activity will be printed in this terminal", flush=True)
    print(f"[startup] routes={route_list}", flush=True)
    print("=" * 72, flush=True)

state_manager = StateManager()
drone: System | None = None
session_log_store: SessionLogStore | None = None
mavsdk_loop: asyncio.AbstractEventLoop | None = None
connection_lock = threading.Lock()
connection_changed = threading.Event()
connection_config = {
    "system_address": MAVSDK_ADDRESS,
    "auto_connect": AUTO_CONNECT,
}

state_manager.update(system_address=MAVSDK_ADDRESS, status="OFFLINE" if AUTO_CONNECT else "DISCONNECTED")
session_log_store = SessionLogStore(system_address=MAVSDK_ADDRESS)


class _MavsdkServerNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        noisy_fragments = (
            "ReadFile failure",
            "Sending message failed",
            "The device does not recognize the command.",
            "serial_connection.cpp:310",
            "mavsdk_impl.cpp:801",
        )
        return not any(fragment in message for fragment in noisy_fragments)


logging.getLogger("mavsdk_server").addFilter(_MavsdkServerNoiseFilter())


class _WerkzeugPollingFilter(logging.Filter):
    """Suppress Werkzeug access log lines for high-frequency polling endpoints."""

    _QUIET_FRAGMENTS = ("/health", "/telemetry")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(frag in msg for frag in self._QUIET_FRAGMENTS)


logging.getLogger("werkzeug").addFilter(_WerkzeugPollingFilter())


class RebootRequestedSignal(Exception):
    pass


class ConnectionConfigChangedSignal(Exception):
    pass


class DisconnectRequestedSignal(Exception):
    pass


def _get_connection_config() -> dict:
    with connection_lock:
        return dict(connection_config)


def _set_connection_target(system_address: str) -> dict:
    with connection_lock:
        connection_config["system_address"] = system_address
        connection_config["auto_connect"] = True
    connection_changed.set()
    return {"message": "Connection target updated"}


def _disconnect_vehicle() -> dict:
    with connection_lock:
        connection_config["auto_connect"] = False
    connection_changed.set()
    return {"message": "Vehicle connection stopped"}


def _pick_mavsdk_server_port() -> int:
    if MAVSDK_SERVER_PORT > 0:
        return MAVSDK_SERVER_PORT

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])

init_command_routes(state_manager, lambda: drone, session_log_store, lambda: mavsdk_loop)
init_mission_routes(state_manager, lambda: drone, session_log_store, lambda: mavsdk_loop)
init_telemetry_routes(state_manager)
init_health_routes(state_manager) 
init_log_routes(session_log_store)
init_connection_routes(state_manager, _set_connection_target, _disconnect_vehicle)

app.register_blueprint(connection_bp)
app.register_blueprint(command_bp)
app.register_blueprint(mission_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(telemetry_bp)
app.register_blueprint(health_bp)


async def _consume_position(drone):
    async for pos in drone.telemetry.position():
        state_manager.update(
            lat=pos.latitude_deg,
            lng=pos.longitude_deg,
            alt=pos.relative_altitude_m,
            alt_amsl=pos.absolute_altitude_m,
            last_update=time.time(),
            error=None,
        )
        if session_log_store is not None:
            session_log_store.record_telemetry(state_manager.get())


async def _consume_armed(drone):
    async for armed in drone.telemetry.armed():
        state_manager.update(armed=armed, last_update=time.time(), error=None)


async def _consume_flight_mode(drone):
    async for mode in drone.telemetry.flight_mode():
        mode_str = str(mode)
        # MAVSDK can't decode ArduPilot-specific modes (QHOVER, FBWA, etc.)
        # and reports them as "UNKNOWN". Skip these to preserve our own
        # mode tracking from successful SET_MODE commands.
        if "UNKNOWN" in mode_str.upper():
            continue
        state_manager.update(flight_mode=mode_str, last_update=time.time(), error=None)


async def _consume_heartbeat_mode(drone):
    async for message in drone.mavlink_direct.message("HEARTBEAT"):
        try:
            fields = json.loads(message.fields_json or "{}")
        except json.JSONDecodeError:
            continue

        custom_mode = fields.get("custom_mode")
        if custom_mode is None:
            continue

        try:
            mode_id = int(custom_mode)
        except (TypeError, ValueError):
            continue

        mode_name = ARDUPILOT_MODE_REVERSE_MAPPING.get(mode_id)
        if not mode_name:
            continue

        current = state_manager.get()
        if current.flight_mode != mode_name:
            print(
                f"[heartbeat] mode={mode_name} custom_mode={mode_id} sysid={message.system_id} compid={message.component_id}",
                flush=True,
            )
        state_manager.update(flight_mode=mode_name, last_update=time.time(), error=None)


async def _consume_battery(drone):
    async for battery in drone.telemetry.battery():
        state_manager.update(
            battery_percent=round(float(battery.remaining_percent) * 100.0, 2),
            last_update=time.time(),
            error=None,
        )


async def _consume_attitude(drone):
    async for attitude in drone.telemetry.attitude_euler():
        state_manager.update(
            roll_deg=round(attitude.roll_deg, 2),
            pitch_deg=round(attitude.pitch_deg, 2),
            yaw_deg=round(attitude.yaw_deg, 2),
            last_update=time.time(),
            error=None,
        )


async def _consume_heading(drone):
    async for heading in drone.telemetry.heading():
        state_manager.update(
            heading_deg=round(heading.heading_deg, 2),
            last_update=time.time(),
            error=None,
        )


async def _consume_velocity(drone):
    async for velocity in drone.telemetry.velocity_ned():
        groundspeed = math.sqrt(velocity.north_m_s ** 2 + velocity.east_m_s ** 2)
        state_manager.update(
            groundspeed_m_s=round(groundspeed, 2),
            v_speed_m_s=round(-velocity.down_m_s, 2),  # NED: down is positive, flip for climb rate
            last_update=time.time(),
            error=None,
        )


async def _watch_reboot_request():
    while True:
        await asyncio.sleep(0.25)
        if state_manager.get().status == "REBOOTING":
            raise RebootRequestedSignal()


async def _watch_connection_change():
    while True:
        await asyncio.sleep(0.2)
        if connection_changed.is_set():
            connection_changed.clear()
            if _get_connection_config()["auto_connect"]:
                raise ConnectionConfigChangedSignal()
            raise DisconnectRequestedSignal()


def _is_serial_disconnect_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "readfile failure" in message
        or "connection reset" in message
        or "access is denied" in message
        or "serial" in message
    )


def _get_retry_delay_seconds(exc: Exception) -> float:
    if _is_serial_disconnect_error(exc):
        return SERIAL_ACCESS_DENIED_RETRY_DELAY_SECONDS
    return RETRY_DELAY_SECONDS


def _get_friendly_error_message(exc: Exception) -> str:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        msg = str(exc)
        return msg if msg else f"No MAVLink heartbeat within {CONNECT_TIMEOUT_SECONDS:.0f}s"
    
    message = str(exc)
    lowered = message.lower()
    if "readfile failure" in lowered or "connection reset" in lowered:
        return "MAVSDK serial connection lost"
    if "access is denied" in lowered:
        return "Serial port is in use or blocked"
    
    return message if message else type(exc).__name__



async def _mavsdk_loop():
    base_delay = 2.0
    max_delay = 10.0
    current_delay = base_delay
    global drone, mavsdk_loop
    mavsdk_loop = asyncio.get_running_loop()
    last_reported_online: bool | None = None

    while True:
        # Explicit cleanup of previous drone instance to avoid process leaks
        if drone is not None:
            try:
                drone._stop_mavsdk_server()
            except Exception:
                pass
            finally:
                drone = None

        try:
            current_config = _get_connection_config()
            if not current_config["auto_connect"]:
                state_manager.update(connected=False, status="DISCONNECTED", error=None, last_update=time.time())
                await asyncio.to_thread(connection_changed.wait)
                connection_changed.clear()
                continue

            system_address = current_config["system_address"]
            mavsdk_server_port = _pick_mavsdk_server_port()
            drone = System(port=mavsdk_server_port)
            state_manager.update(system_address=system_address, mavsdk_server_port=mavsdk_server_port)

            current_state = state_manager.get()
            if current_state.status != "REBOOTING":
                state_manager.update(connected=False, status="CONNECTING", error=None, last_update=time.time())
                if last_reported_online is not False:
                    print(f"[status] connecting to vehicle at {system_address} via MAVSDK gRPC {mavsdk_server_port}...")
                    last_reported_online = False
            else:
                state_manager.update(connected=False, status="REBOOTING", error=None, last_update=time.time())
                if last_reported_online is not False:
                    print(f"[status] vehicle rebooting, waiting to reconnect at {system_address}...")
                    last_reported_online = False

            await asyncio.wait_for(
                drone.connect(system_address=system_address),
                timeout=CONNECT_CALL_TIMEOUT_SECONDS,
            )

            connected = False
            heartbeat_stream = drone.core.connection_state()
            deadline = time.time() + CONNECT_TIMEOUT_SECONDS

            while time.time() < deadline:
                remaining = max(0.1, deadline - time.time())
                connection_state = await asyncio.wait_for(heartbeat_stream.__anext__(), timeout=remaining)
                state_manager.update(connected=connection_state.is_connected, status="ACTIVE" if connection_state.is_connected else "CONNECTING", last_update=time.time())
                if connection_state.is_connected:
                    connected = True
                    if last_reported_online is not True:
                        print(f"[status] vehicle online at {system_address}")
                        last_reported_online = True
                    break

            if not connected:
                raise TimeoutError(
                    f"No MAVLink heartbeat on {system_address} within {CONNECT_TIMEOUT_SECONDS:.0f}s"
                )

            if session_log_store is not None:
                session_log_store.record_event("connection_state", "Vehicle connected", connected=True)
            
            current_delay = base_delay

            consumers = [
                asyncio.create_task(_consume_position(drone)),
                asyncio.create_task(_consume_armed(drone)),
                asyncio.create_task(_consume_flight_mode(drone)),
                asyncio.create_task(_consume_heartbeat_mode(drone)),
                asyncio.create_task(_consume_battery(drone)),
                asyncio.create_task(_consume_attitude(drone)),
                asyncio.create_task(_consume_heading(drone)),
                asyncio.create_task(_consume_velocity(drone)),
                asyncio.create_task(_watch_reboot_request()),
                asyncio.create_task(_watch_connection_change()),
            ]

            done, pending = await asyncio.wait(consumers, return_when=asyncio.FIRST_EXCEPTION)
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc

        except Exception as exc:
            current_state = state_manager.get()
            active_config = _get_connection_config()
            active_address = active_config["system_address"]
            if isinstance(exc, DisconnectRequestedSignal):
                state_manager.update(connected=False, status="DISCONNECTED", error=None, last_update=time.time())
                if drone is not None:
                    try:
                        drone._stop_mavsdk_server()
                    except Exception:
                        pass
                    finally:
                        drone = None
                current_delay = base_delay
                continue
            if isinstance(exc, ConnectionConfigChangedSignal):
                state_manager.update(connected=False, status="CONNECTING", error=None, last_update=time.time())
                if drone is not None:
                    try:
                        drone._stop_mavsdk_server()
                    except Exception:
                        pass
                    finally:
                        drone = None
                current_delay = base_delay
                continue
            if isinstance(exc, RebootRequestedSignal) or current_state.status == "REBOOTING":
                friendly_error = "Vehicle rebooting"
                state_manager.update(connected=False, status="REBOOTING", error=None, last_update=time.time())
                if session_log_store is not None:
                    session_log_store.record_event(
                        "connection_state",
                        friendly_error,
                        system_address=active_address,
                    )
            else:
                friendly_error = _get_friendly_error_message(exc)
                state_manager.update(connected=False, status="OFFLINE", error=friendly_error, last_update=time.time())
                if session_log_store is not None:
                    session_log_store.record_event(
                        "connection_error",
                        friendly_error,
                        error=friendly_error,
                        system_address=active_address,
                    )

            if current_state.status == "REBOOTING" or isinstance(exc, RebootRequestedSignal):
                print(f"[status] vehicle rebooting, reconnecting to {active_address}...")
            elif last_reported_online is not False:
                print(f"[status] vehicle disconnected: {friendly_error}")
                last_reported_online = False
            
            # Enhanced cleanup: explicitly stop and delete the drone object
            if drone is not None:
                try:
                    drone._stop_mavsdk_server()
                except Exception:
                    pass
                finally:
                    drone = None

            retry_delay = max(current_delay, _get_retry_delay_seconds(exc))
            jitter = random.uniform(-0.1, 0.1) * retry_delay
            sleep_time = retry_delay + jitter
            print(f"Connection error: {friendly_error}. Retrying in {sleep_time:.1f} seconds...")
            try:
                await asyncio.wait_for(asyncio.to_thread(connection_changed.wait), timeout=sleep_time)
                connection_changed.clear()
                current_delay = base_delay
                continue
            except asyncio.TimeoutError:
                pass
            current_delay = min(current_delay * 2, max_delay)


def _start_mavsdk_background_thread():
    def runner():
        asyncio.run(_mavsdk_loop())

    import threading

    thread = threading.Thread(target=runner, daemon=True, name="mavsdk-reader")
    thread.start()

if __name__ == "__main__":
    _print_startup_banner()
    _start_mavsdk_background_thread()
    app.run(host="127.0.0.1", port=API_PORT, threaded=True)
