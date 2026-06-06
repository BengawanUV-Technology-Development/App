import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Blueprint, abort, jsonify, send_file


map_tiles_bp = Blueprint("map_tiles", __name__, url_prefix="/api/v1/map")
DEFAULT_TILE_SOURCE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
TILE_REQUEST_TIMEOUT_SECONDS = 4.0


def _tile_root():
    configured = os.getenv("MAP_TILE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "runtime" / "map-tiles").resolve()


def _tile_source_url():
    return os.getenv("MAP_TILE_SOURCE_URL", DEFAULT_TILE_SOURCE_URL)


def _cache_max_age_seconds():
    try:
        return max(0, int(os.getenv("MAP_TILE_CACHE_MAX_AGE_SECONDS", str(DEFAULT_CACHE_MAX_AGE_SECONDS))))
    except ValueError:
        return DEFAULT_CACHE_MAX_AGE_SECONDS


def _tile_is_fresh(tile_path):
    return tile_path.is_file() and time.time() - tile_path.stat().st_mtime <= _cache_max_age_seconds()


def _download_tile(zoom, x, y, tile_path):
    source_url = _tile_source_url().format(z=zoom, x=x, y=y)
    request = Request(source_url, headers={"User-Agent": "BUV-Operational-Console/0.1"})
    with urlopen(request, timeout=TILE_REQUEST_TIMEOUT_SECONDS) as response:
        content_type = response.headers.get_content_type()
        tile_data = response.read()
    if content_type != "image/png" or not tile_data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Tile source did not return a PNG image")

    tile_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = tile_path.with_suffix(".png.tmp")
    temporary_path.write_bytes(tile_data)
    temporary_path.replace(tile_path)


@map_tiles_bp.route("/tiles/<int:zoom>/<int:x>/<int:y>.png", methods=["GET"])
def local_map_tile(zoom, x, y):
    tile_limit = 2 ** zoom if 0 <= zoom <= 22 else 0
    if not tile_limit or not 0 <= x < tile_limit or not 0 <= y < tile_limit:
        abort(404)

    tile_path = _tile_root() / str(zoom) / str(x) / f"{y}.png"
    if not _tile_is_fresh(tile_path):
        try:
            _download_tile(zoom, x, y, tile_path)
        except (HTTPError, URLError, OSError, ValueError):
            if not tile_path.is_file():
                abort(503, description="Map tile unavailable online and not present in local cache")

    return send_file(tile_path, mimetype="image/png", conditional=True, max_age=86400)


@map_tiles_bp.route("/config", methods=["GET"])
def map_config():
    root = _tile_root()
    return jsonify({
        "ok": True,
        "tile_mode": "online-with-folder-cache",
        "tile_path": str(root),
        "tile_url": "/api/v1/map/tiles/{z}/{x}/{y}.png",
        "tile_source_url": _tile_source_url(),
        "cache_max_age_seconds": _cache_max_age_seconds(),
        "exists": root.is_dir(),
    })
