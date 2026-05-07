# src-tauri/src-python/main.py
import asyncio
import logging
import os
import time
import random
from flask import Flask, jsonify
from flask_cors import CORS
from mavsdk import System
from app.routes.mission import mission_bp, init_mission_routes
from app.routes.logs import logs_bp, init_log_routes
from app.routes.telemetry import telemetry_bp, init_telemetry_routes
from app.routes.health import health_bp, init_health_routes
from app.routes.commands import command_bp, init_command_routes
from app.utils.state import StateManager
from app.utils.session_log import SessionLogStore

MAVSDK_ADDRESS = os.getenv("MAVSDK_ADDRESS", "serial://COM10:115200")
API_PORT = int(os.getenv("API_PORT", "5001"))
CONNECT_TIMEOUT_SECONDS = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "8"))
CONNECT_CALL_TIMEOUT_SECONDS = float(os.getenv("CONNECT_CALL_TIMEOUT_SECONDS", "15"))
RETRY_DELAY_SECONDS = float(os.getenv("RETRY_DELAY_SECONDS", "5"))
SERIAL_ACCESS_DENIED_RETRY_DELAY_SECONDS = float(
    os.getenv("SERIAL_ACCESS_DENIED_RETRY_DELAY_SECONDS", "10")
)


app = Flask(__name__)
CORS(app)

state_manager = StateManager()
drone: System | None = None
session_log_store: SessionLogStore | None = None
mavsdk_loop: asyncio.AbstractEventLoop | None = None

state_manager.update(system_address=MAVSDK_ADDRESS)
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


class RebootRequestedSignal(Exception):
    pass

init_command_routes(state_manager, lambda: drone, session_log_store, lambda: mavsdk_loop)
init_mission_routes(state_manager, lambda: drone, session_log_store, lambda: mavsdk_loop)
init_telemetry_routes(state_manager)
init_health_routes(state_manager) 
init_log_routes(session_log_store)

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
        state_manager.update(flight_mode=str(mode), last_update=time.time(), error=None)


async def _consume_battery(drone):
    async for battery in drone.telemetry.battery():
        state_manager.update(
            battery_percent=round(float(battery.remaining_percent) * 100.0, 2),
            last_update=time.time(),
            error=None,
        )


async def _watch_reboot_request():
    while True:
        await asyncio.sleep(0.25)
        if state_manager.get().status == "REBOOTING":
            raise RebootRequestedSignal()


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
    message = str(exc)
    lowered = message.lower()
    if "readfile failure" in lowered or "connection reset" in lowered:
        return "MAVSDK serial connection lost"
    if "access is denied" in lowered:
        return "Serial port is in use or blocked"
    return message


async def _mavsdk_loop():
    base_delay = 2.0
    max_delay = 10.0
    current_delay = base_delay
    global drone, mavsdk_loop
    mavsdk_loop = asyncio.get_running_loop()
    last_reported_online: bool | None = None

    while True:
        try:
            drone = System()

            current_state = state_manager.get()
            if current_state.status != "REBOOTING":
                state_manager.update(connected=False, status="CONNECTING", error=None, last_update=time.time())
                if last_reported_online is not False:
                    print(f"[status] connecting to vehicle at {MAVSDK_ADDRESS}...")
                    last_reported_online = False
            else:
                state_manager.update(connected=False, status="REBOOTING", error=None, last_update=time.time())
                if last_reported_online is not False:
                    print(f"[status] vehicle rebooting, waiting to reconnect at {MAVSDK_ADDRESS}...")
                    last_reported_online = False

            await asyncio.wait_for(
                drone.connect(system_address=MAVSDK_ADDRESS),
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
                        print(f"[status] vehicle online at {MAVSDK_ADDRESS}")
                        last_reported_online = True
                    break

            if not connected:
                raise TimeoutError(
                    f"No MAVLink heartbeat on {MAVSDK_ADDRESS} within {CONNECT_TIMEOUT_SECONDS:.0f}s"
                )

            if session_log_store is not None:
                session_log_store.record_event("connection_state", "Vehicle connected", connected=True)
            
            current_delay = base_delay

            consumers = [
                asyncio.create_task(_consume_position(drone)),
                asyncio.create_task(_consume_armed(drone)),
                asyncio.create_task(_consume_flight_mode(drone)),
                asyncio.create_task(_consume_battery(drone)),
                asyncio.create_task(_watch_reboot_request()),
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
            if isinstance(exc, RebootRequestedSignal) or current_state.status == "REBOOTING":
                friendly_error = "Vehicle rebooting"
                state_manager.update(connected=False, status="REBOOTING", error=None, last_update=time.time())
                if session_log_store is not None:
                    session_log_store.record_event(
                        "connection_state",
                        friendly_error,
                        system_address=MAVSDK_ADDRESS,
                    )
            else:
                friendly_error = _get_friendly_error_message(exc)
                state_manager.update(connected=False, status="OFFLINE", error=friendly_error, last_update=time.time())
                if session_log_store is not None:
                    session_log_store.record_event(
                        "connection_error",
                        friendly_error,
                        error=friendly_error,
                        system_address=MAVSDK_ADDRESS,
                    )

            if current_state.status == "REBOOTING" or isinstance(exc, RebootRequestedSignal):
                print(f"[status] vehicle rebooting, reconnecting to {MAVSDK_ADDRESS}...")
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
            await asyncio.sleep(sleep_time)
            current_delay = min(current_delay * 2, max_delay)


def _start_mavsdk_background_thread():
    def runner():
        asyncio.run(_mavsdk_loop())

    import threading

    thread = threading.Thread(target=runner, daemon=True, name="mavsdk-reader")
    thread.start()

if __name__ == "__main__":
    _start_mavsdk_background_thread()
    app.run(host="127.0.0.1", port=API_PORT, threaded=True)
