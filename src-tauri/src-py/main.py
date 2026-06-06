import json
import logging
import os
import time

from flask import Flask, request
from flask_cors import CORS
from flask_sock import Sock

from app.routes.api_v1 import api_v1_bp, init_api_v1_routes
from app.routes.logs import init_log_routes, logs_bp
from app.routes.map_tiles import map_tiles_bp
from app.services.mission_planner_adapter import MissionPlannerAdapter
from app.utils.session_log import SessionLogStore


API_PORT = int(os.getenv("API_PORT", "5001"))

app = Flask(__name__)
CORS(app)
sock = Sock(app)

mission_planner_adapter = MissionPlannerAdapter()
session_log_store = SessionLogStore(source_address=mission_planner_adapter.base_url)

init_api_v1_routes(mission_planner_adapter)
init_log_routes(session_log_store)
app.register_blueprint(api_v1_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(map_tiles_bp)


class _WerkzeugPollingFilter(logging.Filter):
    _QUIET_FRAGMENTS = ("/api/v1/health", "/api/v1/telemetry")

    def filter(self, record: logging.LogRecord) -> bool:
        return not any(fragment in record.getMessage() for fragment in self._QUIET_FRAGMENTS)


logging.getLogger("werkzeug").addFilter(_WerkzeugPollingFilter())


@app.before_request
def _log_http_request():
    if request.path in {"/api/v1/health", "/api/v1/telemetry"}:
        return
    payload = request.get_json(silent=True) if request.method in {"POST", "PUT", "PATCH"} else None
    print(f"[http] -> {request.method} {request.path} payload={payload or '-'}", flush=True)


@app.after_request
def _log_http_response(response):
    if request.path not in {"/api/v1/health", "/api/v1/telemetry"}:
        print(f"[http] <- {request.method} {request.path} status={response.status_code}", flush=True)
    return response


@sock.route("/api/v1/events")
def api_v1_events(ws):
    last_version = None
    try:
        while True:
            snapshot = mission_planner_adapter.snapshot()
            if snapshot["version"] != last_version:
                ws.send(json.dumps({
                    "type": "telemetry.updated",
                    "timestamp": time.time(),
                    "data": snapshot,
                }))
                last_version = snapshot["version"]
            time.sleep(0.1)
    except Exception:
        return


def _print_startup_banner():
    route_list = ", ".join(sorted(rule.rule for rule in app.url_map.iter_rules()))
    print("=" * 72, flush=True)
    print(f"[startup] BUV backend pid={os.getpid()} cwd={os.getcwd()}", flush=True)
    print(f"[startup] api=http://127.0.0.1:{API_PORT}", flush=True)
    print(f"[startup] mission_planner={mission_planner_adapter.base_url}", flush=True)
    print(f"[startup] routes={route_list}", flush=True)
    print("=" * 72, flush=True)


if __name__ == "__main__":
    _print_startup_banner()
    mission_planner_adapter.start()
    app.run(host="127.0.0.1", port=API_PORT, threaded=True)
