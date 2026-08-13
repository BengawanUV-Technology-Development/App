#!/usr/bin/env bash
# Installs the system libraries the Jetson RTP video receiver needs on macOS
# (app/services/jetson_video_service.py imports GStreamer via "import gi",
# which is a C-extension binding and cannot be satisfied by pip alone).
#
# Usage: scripts/setup_macos_video_deps.sh [path-to-venv]
# Defaults to ./venv relative to this script's src-py directory.
set -Eeuo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "[setup] this script is macOS-only; on Linux/Docker use apt (see Dockerfile)" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_PY_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="${1:-$SRC_PY_DIR/venv}"

if ! command -v brew >/dev/null 2>&1; then
  echo "[setup] Homebrew not found; installing (non-interactive)..."
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
fi

echo "[setup] installing GStreamer + PyGObject system libraries via Homebrew..."
brew install pkg-config gobject-introspection pygobject3 \
  gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[setup] creating venv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

echo "[setup] installing Python requirements into $VENV_DIR"
"$VENV_DIR/bin/python3" -m pip install -q -r "$SRC_PY_DIR/requirements.txt"

echo "[setup] verifying gi import..."
"$VENV_DIR/bin/python3" -c "import gi; gi.require_version('Gst', '1.0'); from gi.repository import Gst; Gst.init([]); print('[setup] gi + GStreamer OK:', Gst.version_string())"

echo "[setup] done."
