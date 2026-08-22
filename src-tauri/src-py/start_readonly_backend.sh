#!/usr/bin/env bash
set -euo pipefail

backend_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$backend_dir"

export PYTHONPATH="$backend_dir${PYTHONPATH:+:$PYTHONPATH}"
export API_HOST="${API_HOST:-127.0.0.1}"
export API_PORT="${API_PORT:-5001}"
export MAVLINK_UDP_HOST="${MAVLINK_UDP_HOST:-127.0.0.1}"
export MAVLINK_UDP_PORT="${MAVLINK_UDP_PORT:-14551}"
export SESSION_LOG_DIR="${SESSION_LOG_DIR:-$backend_dir/runtime/logs}"

exec python3 main.py
