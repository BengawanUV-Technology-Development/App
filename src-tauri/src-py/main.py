# src-tauri/src-python/main.py
import asyncio
import logging
import os
import time
import random
import math
import threading
from flask import Flask, jsonify
from flask_cors import CORS
from mavsdk import System
from app.routes.mission import mission_bp, init_mission_routes
from app.routes.logs import logs_bp, init_log_routes
from app.routes.telemetry import telemetry_bp, init_telemetry_routes
from app.routes.health import health_bp, init_health_routes
from app.routes.commands import command_bp, init_command_routes
from app.utils.logger import logger
from app.utils.state import StateManager
from app.utils.session_log import SessionLogStore

MAVSDK_ADDRESS = os.getenv("MAVSDK_ADDRESS", "serial://COM9:115200")
API_PORT = int(os.getenv("API_PORT", "5001"))
CONNECT_TIMEOUT_SECONDS = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "8"))
CONNECT_CALL_TIMEOUT_SECONDS = float(os.getenv("CONNECT_CALL_TIMEOUT_SECONDS", "15"))
RETRY_DELAY_SECONDS = float(os.getenv("RETRY_DELAY_SECONDS", "5"))

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
        noisy_fragments = ("ReadFile failure", "Sending message failed", "serial_connection.cpp", "mavsdk_impl.cpp")
        return not any(fragment in message for fragment in noisy_fragments)

logging.getLogger("mavsdk_server").addFilter(_MavsdkServerNoiseFilter())

class RebootRequestedSignal(Exception): pass
class ConnectionAddressChangedSignal(Exception): pass

def update_mavsdk_address(new_address: str):
    global MAVSDK_ADDRESS
    if "://" not in new_address:
        if new_address.upper().startswith("COM") or new_address.startswith("/dev/"):
            new_address = f"serial://{new_address}:115200"
        elif ":" in new_address:
            # Modern MAVSDK prefers udpin for listening
            new_address = f"udpin://0.0.0.0:{new_address.split(':')[-1]}"
    
    # Standardize deprecated udp:// to udpin://
    if new_address.startswith("udp://"):
        new_address = new_address.replace("udp://", "udpin://0.0.0.0:", 1).replace("::", ":")

    if new_address != MAVSDK_ADDRESS:
        MAVSDK_ADDRESS = new_address
        state_manager.update(system_address=MAVSDK_ADDRESS)
        return True
    return False

init_command_routes(state_manager, lambda: drone, session_log_store, lambda: mavsdk_loop, update_mavsdk_address)
init_mission_routes(state_manager, lambda: drone, session_log_store, lambda: mavsdk_loop)
init_telemetry_routes(state_manager)
init_health_routes(state_manager) 
init_log_routes(session_log_store)

app.register_blueprint(command_bp)
app.register_blueprint(mission_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(telemetry_bp)
app.register_blueprint(health_bp)

# --- TELEMETRY CONSUMERS ---

async def _consume_position(drone):
    async for pos in drone.telemetry.position():
        state_manager.update(lat=pos.latitude_deg, lng=pos.longitude_deg, alt=pos.relative_altitude_m, last_update=time.time())

async def _consume_armed(drone):
    async for armed in drone.telemetry.armed():
        state_manager.update(armed=armed, last_update=time.time())

async def _consume_flight_mode(drone):
    async for mode in drone.telemetry.flight_mode():
        state_manager.update(flight_mode=str(mode), last_update=time.time())

async def _consume_battery(drone):
    async for battery in drone.telemetry.battery():
        state_manager.update(battery_percent=round(float(battery.remaining_percent) * 100.0, 2), last_update=time.time())

async def _consume_attitude(drone):
    async for att in drone.telemetry.attitude_euler():
        state_manager.update(roll_deg=round(att.roll_deg, 2), pitch_deg=round(att.pitch_deg, 2), yaw_deg=round(att.yaw_deg, 2), last_update=time.time())

async def _consume_velocity(drone):
    async for vel in drone.telemetry.velocity_ned():
        gs = math.sqrt(vel.north_m_s**2 + vel.east_m_s**2)
        state_manager.update(groundspeed_m_s=round(gs, 2), v_speed_m_s=round(-vel.down_m_s, 2), last_update=time.time())

async def _consume_heading(drone):
    async for h in drone.telemetry.heading():
        state_manager.update(heading_deg=round(h.heading_deg, 2), last_update=time.time())

async def _consume_status_text(drone):
    async for status in drone.telemetry.status_text():
        msg_type = str(status.type).replace('STATUS_TEXT_TYPE_', '')
        msg = f"[{msg_type}] {status.text}"
        state_manager.update(status_text=msg, last_update=time.time())
        state_manager.append_status_text(status.text, msg_type)
        if session_log_store: session_log_store.record_event("status_text", msg)

async def _consume_health(drone):
    async for health in drone.telemetry.health():
        state_manager.update_prearm_health(
            is_gyrometer_calibration_ok=health.is_gyrometer_calibration_ok,
            is_accelerometer_calibration_ok=health.is_accelerometer_calibration_ok,
            is_magnetometer_calibration_ok=health.is_magnetometer_calibration_ok,
            is_local_position_ok=health.is_local_position_ok,
            is_global_position_ok=health.is_global_position_ok,
            is_home_position_ok=health.is_home_position_ok,
            is_armable=health.is_armable,
        )

async def _run_safe_consumer(name, coro_func, drone_obj):
    while True:
        try:
            await coro_func(drone_obj)
        except Exception as e:
            logger.error(f"Consumer {name} error: {e}")
            await asyncio.sleep(1)

async def _mavsdk_loop():
    global drone, mavsdk_loop
    mavsdk_loop = asyncio.get_running_loop()
    
    while True:
        try:
            drone = System()
            state_manager.update(connected=False, status="CONNECTING")
            
            print(f"[status] connecting to {MAVSDK_ADDRESS}...")
            await asyncio.wait_for(drone.connect(system_address=MAVSDK_ADDRESS), timeout=10)
            
            # Wait for connection
            async for state in drone.core.connection_state():
                if state.is_connected:
                    break
            
            state_manager.update(connected=True, status="ACTIVE")
            print(f"[status] vehicle online")

            tasks = [
                asyncio.create_task(_run_safe_consumer("pos", _consume_position, drone)),
                asyncio.create_task(_run_safe_consumer("arm", _consume_armed, drone)),
                asyncio.create_task(_run_safe_consumer("mode", _consume_flight_mode, drone)),
                asyncio.create_task(_run_safe_consumer("batt", _consume_battery, drone)),
                asyncio.create_task(_run_safe_consumer("att", _consume_attitude, drone)),
                asyncio.create_task(_run_safe_consumer("vel", _consume_velocity, drone)),
                asyncio.create_task(_run_safe_consumer("head", _consume_heading, drone)),
                asyncio.create_task(_run_safe_consumer("text", _consume_status_text, drone)),
                asyncio.create_task(_run_safe_consumer("health", _consume_health, drone)),
            ]
            
            # Watch for address changes or manual reboots
            while True:
                await asyncio.sleep(1)
                if MAVSDK_ADDRESS != state_manager.get().system_address:
                    print("[status] address changed, reconnecting...")
                    break
                if state_manager.get().status == "REBOOTING":
                    break
            
            for t in tasks: t.cancel()
            
        except Exception as e:
            print(f"[error] loop error: {e}")
            state_manager.update(connected=False, status="OFFLINE", error=str(e))
            await asyncio.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(_mavsdk_loop()), daemon=True).start()
    app.run(host="127.0.0.1", port=API_PORT, threaded=True)
