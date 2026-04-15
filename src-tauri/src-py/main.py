# src-tauri/src-python/main.py
import asyncio
import os
import time

from flask import Flask, jsonify
from flask_cors import CORS
from mavsdk import System
from app.routes.telemetry import telemetry_bp, init_telemetry_routes
from app.routes.health import health_bp, init_health_routes
from app.routes.commands import command_bp, init_command_routes
from app.utils.state import StateManager


app = Flask(__name__)
CORS(app)

state_manager = StateManager()
drone = System()

init_command_routes(state_manager, drone)
init_telemetry_routes(state_manager)
init_health_routes(state_manager) 

app.register_blueprint(command_bp)
app.register_blueprint(telemetry_bp)
app.register_blueprint(health_bp)

MAVSDK_ADDRESS = os.getenv("MAVSDK_ADDRESS", "serial://COM9:115200")
API_PORT = int(os.getenv("API_PORT", "5001"))
CONNECT_TIMEOUT_SECONDS = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "8"))
CONNECT_CALL_TIMEOUT_SECONDS = float(os.getenv("CONNECT_CALL_TIMEOUT_SECONDS", "5"))

state_manager.update(system_address=MAVSDK_ADDRESS)


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


async def _mavsdk_loop():
    while True:
        try:
            state_manager.update(connected=False, error=None, last_update=time.time())
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
                state_manager.update(connected=connection_state.is_connected, last_update=time.time())
                if connection_state.is_connected:
                    connected = True
                    break

            if not connected:
                raise TimeoutError(
                    f"No MAVLink heartbeat on {MAVSDK_ADDRESS} within {CONNECT_TIMEOUT_SECONDS:.0f}s"
                )

            consumers = [
                asyncio.create_task(_consume_position(drone)),
                asyncio.create_task(_consume_armed(drone)),
                asyncio.create_task(_consume_flight_mode(drone)),
                asyncio.create_task(_consume_battery(drone)),
            ]

            done, pending = await asyncio.wait(consumers, return_when=asyncio.FIRST_EXCEPTION)
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc

        except Exception as exc:
            state_manager.update(connected=False, error=str(exc), last_update=time.time())
            await asyncio.sleep(2)


def _start_mavsdk_background_thread():
    def runner():
        asyncio.run(_mavsdk_loop())

    import threading

    thread = threading.Thread(target=runner, daemon=True, name="mavsdk-reader")
    thread.start()

if __name__ == "__main__":
    _start_mavsdk_background_thread()
    app.run(host="127.0.0.1", port=API_PORT, threaded=True)