#!/usr/bin/env bash
set -euo pipefail

backend_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$backend_dir"

export PYTHONPATH="$backend_dir${PYTHONPATH:+:$PYTHONPATH}"
# app.config loads camera.env before applying its own defaults. Do not seed
# API/MAVLink variables here, otherwise camera.env could never select a
# Tailscale-reachable API_HOST for Jetson callbacks.
export SESSION_LOG_DIR="${SESSION_LOG_DIR:-$backend_dir/runtime/logs}"

exec python3 main.py
