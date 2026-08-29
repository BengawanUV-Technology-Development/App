# src-tauri/src-py/main.py
import logging

from flask import Flask
from flask_cors import CORS

from app.routes.camera import camera_bp, init_camera_routes
from app.routes.recording import init_recording_routes, recording_bp
from app.routes.capabilities import capabilities_bp
from app.routes.mission import mission_bp
from app.routes.logs import logs_bp, init_log_routes
from app.routes.telemetry import telemetry_bp, init_telemetry_routes
from app.routes.health import health_bp, init_health_routes
from app.routes.commands import command_bp
from app.routes.vision import init_vision_routes, vision_bp
from app.services.readonly_mavlink import ReadonlyMavlinkReceiver
from app.services.camera_stream import CameraStreamService
from app.services.jetson_recording import JetsonRecordingClient
from app.services.mission_telemetry import MissionTelemetryRecorder
from app.services.vision_ingest import VisionDetectionService
from postflight.coordinate_reconstruction import (
    CameraCalibration,
    CoordinateReconstructionAdapter,
)
from app.config import (
    API_HOST,
    API_PORT,
    JETSON_GCS_HOST,
    JETSON_RECORDING_AGENT_TIMEOUT_SECONDS,
    JETSON_RECORDING_AGENT_TOKEN,
    JETSON_RECORDING_AGENT_URL,
    VISION_ALTITUDE_REFERENCE,
    VISION_CAMERA_ATTITUDE_FRAME,
    VISION_COORDINATE_CALIBRATION_PATH,
    VISION_COORDINATE_ENABLED,
    VISION_INGEST_TOKEN,
    VISION_RECENT_DETECTION_LIMIT,
    VISION_TIMELINE_SIZE,
    MAVLINK_UDP_HOST,
    MAVLINK_UDP_PORT,
    mavlink_udp_address,
)
from app.utils.state import StateManager
from app.utils.session_log import SessionLogStore

logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

state_manager = StateManager()
telemetry_address = mavlink_udp_address()
state_manager.update(
    source="mavlink-udp-readonly",
    system_address=telemetry_address,
)
session_log_store = SessionLogStore(system_address=telemetry_address)
mission_telemetry_recorder = MissionTelemetryRecorder()
camera_service = CameraStreamService()

calibration = None
if VISION_COORDINATE_CALIBRATION_PATH:
    try:
        calibration = CameraCalibration.from_json(VISION_COORDINATE_CALIBRATION_PATH)
    except Exception as exc:
        logger.warning("Vision calibration is unavailable: %s", exc)
coordinate_adapter = CoordinateReconstructionAdapter(calibration)
vision_service = VisionDetectionService(
    coordinate_adapter=coordinate_adapter,
    coordinate_enabled=VISION_COORDINATE_ENABLED,
    altitude_reference=VISION_ALTITUDE_REFERENCE,
    camera_attitude_frame=VISION_CAMERA_ATTITUDE_FRAME,
    timeline_size=VISION_TIMELINE_SIZE,
    recent_detection_limit=VISION_RECENT_DETECTION_LIMIT,
)
jetson_recording_client = JetsonRecordingClient(
    base_url=JETSON_RECORDING_AGENT_URL,
    token=JETSON_RECORDING_AGENT_TOKEN,
    timeout=JETSON_RECORDING_AGENT_TIMEOUT_SECONDS,
    gcs_host=JETSON_GCS_HOST,
)

# Deliberately do not initialize CommandService/MissionService.  Their route
# blueprints are registered only so a caller receives an explicit 403 from the
# read-only guard instead of accidentally falling back to a writable endpoint.
init_telemetry_routes(state_manager)
init_health_routes(state_manager) 
init_log_routes(session_log_store)
init_camera_routes(camera_service)
init_recording_routes(
    camera_service,
    jetson_recording_client,
    state_manager=state_manager,
    mission_recorder=mission_telemetry_recorder,
    vision_service=vision_service,
)
init_vision_routes(vision_service, VISION_INGEST_TOKEN)

app.register_blueprint(command_bp)
app.register_blueprint(mission_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(telemetry_bp)
app.register_blueprint(health_bp)
app.register_blueprint(capabilities_bp)
app.register_blueprint(camera_bp)
app.register_blueprint(recording_bp)
app.register_blueprint(vision_bp)

mavlink_receiver = ReadonlyMavlinkReceiver(
    state_manager=state_manager,
    session_log_store=session_log_store,
    host=MAVLINK_UDP_HOST,
    port=MAVLINK_UDP_PORT,
    mission_recorder=mission_telemetry_recorder,
    telemetry_observer=vision_service.record_telemetry,
)

if __name__ == "__main__":
    mavlink_receiver.start()
    try:
        app.run(host=API_HOST, port=API_PORT, threaded=True)
    finally:
        mavlink_receiver.stop()
        vision_service.stop()
        mission_telemetry_recorder.stop(reason="backend_shutdown")
