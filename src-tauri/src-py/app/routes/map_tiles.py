import os
from pathlib import Path

from flask import Blueprint, abort, jsonify, send_file


map_tiles_bp = Blueprint("map_tiles", __name__, url_prefix="/api/v1/map")


def _tile_root():
    configured = os.getenv("MAP_TILE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "runtime" / "map-tiles").resolve()


@map_tiles_bp.route("/tiles/<int:zoom>/<int:x>/<int:y>.png", methods=["GET"])
def local_map_tile(zoom, x, y):
    if not 0 <= zoom <= 22 or x < 0 or y < 0:
        abort(404)

    tile_path = _tile_root() / str(zoom) / str(x) / f"{y}.png"
    if not tile_path.is_file():
        abort(404)
    return send_file(tile_path, mimetype="image/png", conditional=True, max_age=86400)


@map_tiles_bp.route("/config", methods=["GET"])
def map_config():
    root = _tile_root()
    return jsonify({
        "ok": True,
        "tile_mode": "local-folder",
        "tile_path": str(root),
        "tile_url": "/api/v1/map/tiles/{z}/{x}/{y}.png",
        "exists": root.is_dir(),
    })
