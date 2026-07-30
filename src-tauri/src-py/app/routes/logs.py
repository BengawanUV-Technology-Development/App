import logging

from flask import Blueprint, abort, jsonify, request

from app.utils.session_log import SessionLogStore


logs_bp = Blueprint("logs", __name__, url_prefix="/logs")
_session_log_store: SessionLogStore | None = None
logger = logging.getLogger(__name__)


def init_log_routes(session_log_store: SessionLogStore):
    global _session_log_store
    _session_log_store = session_log_store


def _get_store_or_abort():
    if _session_log_store is None:
        abort(500, description="Log routes not initialized")
    return _session_log_store


@logs_bp.route("/summary", methods=["GET"])
def log_summary():
    """
    Get session log summary.
    ---
    responses:
      200:
        description: Returns a summary of the current session
    """
    store = _get_store_or_abort()
    return jsonify({"ok": True, "session": store.summary()})


@logs_bp.route("/recent", methods=["GET"])
def recent_logs():
    """
    Get recent log events.
    ---
    parameters:
      - name: limit
        in: query
        type: integer
        required: false
        default: 50
        description: Maximum number of events to return
    responses:
      200:
        description: Returns a list of recent log events
    """
    store = _get_store_or_abort()
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))

    events = store.recent_events(limit)
    logger.info("log_request recent limit=%s count=%s", limit, len(events))
    return jsonify({"ok": True, "count": len(events), "items": events})