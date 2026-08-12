#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  jetson/replay_recording.sh EPOCH_DIR [options]

Options:
  --delay-ms N       Artificial metadata delay; default 0
  --speed N          Replay speed multiplier; default 1
  --ground-host IP   Ground laptop Tailscale IP; default 100.114.81.87
  --record-dir DIR   Temporary output directory; default /tmp/buv-replay
  --env-file FILE    Root environment file; default /etc/buv/jetson-recording-v03.env
  -h, --help         Show this help

EPOCH_DIR must contain video.mp4 and detections.jsonl.
EOF
}

die() {
  echo "[replay] ERROR: $*" >&2
  exit 2
}

if [[ $# -eq 0 ]]; then
  usage >&2
  exit 2
fi
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  usage
  exit 0
fi
EPOCH_DIR=$(realpath "$1")
shift
DELAY_MS=0
SPEED=1
GROUND_HOST=${REPLAY_GROUND_HOST:-100.114.81.87}
RECORD_DIR=${REPLAY_RECORD_DIR:-/tmp/buv-replay}
ENV_FILE=${JETSON_REPLAY_ENV_FILE:-/etc/buv/jetson-recording-v03.env}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --delay-ms)
      [[ $# -ge 2 ]] || die "--delay-ms requires a value"
      DELAY_MS=$2
      shift 2
      ;;
    --speed)
      [[ $# -ge 2 ]] || die "--speed requires a value"
      SPEED=$2
      shift 2
      ;;
    --ground-host)
      [[ $# -ge 2 ]] || die "--ground-host requires a value"
      GROUND_HOST=$2
      shift 2
      ;;
    --record-dir)
      [[ $# -ge 2 ]] || die "--record-dir requires a value"
      RECORD_DIR=$(realpath -m "$2")
      shift 2
      ;;
    --env-file)
      [[ $# -ge 2 ]] || die "--env-file requires a value"
      ENV_FILE=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

VIDEO="$EPOCH_DIR/video.mp4"
DETECTIONS="$EPOCH_DIR/detections.jsonl"
[[ -f "$VIDEO" ]] || die "video.mp4 not found in $EPOCH_DIR"
[[ -f "$DETECTIONS" ]] || die "detections.jsonl not found in $EPOCH_DIR"

# systemd receives this secret from a root-only EnvironmentFile. Load only the
# one value needed here and never print it or write it to a log.
if [[ -z "${JETSON_INGEST_TOKEN:-}" ]]; then
  [[ -f "$ENV_FILE" ]] || die "environment file not found: $ENV_FILE"
  JETSON_INGEST_TOKEN=$(sudo awk -F= \
    '$1=="JETSON_INGEST_TOKEN"{print substr($0,index($0,"=")+1); exit}' \
    "$ENV_FILE" | tr -d '\r')
  export JETSON_INGEST_TOKEN
fi
[[ -n "$JETSON_INGEST_TOKEN" ]] || die "JETSON_INGEST_TOKEN is empty"

if command -v ffprobe >/dev/null 2>&1; then
  VIDEO_SIZE=$(ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height -of csv=p=0:s=x "$VIDEO" 2>/dev/null || true)
else
  VIDEO_SIZE=""
fi
if [[ "$VIDEO_SIZE" =~ ^[0-9]+x[0-9]+$ ]]; then
  HIGH_WIDTH=${VIDEO_SIZE%x*}
  HIGH_HEIGHT=${VIDEO_SIZE#*x}
else
  HIGH_WIDTH=${REPLAY_HIGH_WIDTH:-1920}
  HIGH_HEIGHT=${REPLAY_HIGH_HEIGHT:-1080}
fi

MISSION_ID="mission-$(python3 -c 'import uuid; print(uuid.uuid4())')"
REPLAY_DIR="$RECORD_DIR/$MISSION_ID"
mkdir -p "$RECORD_DIR"
PIPELINE_LOG="$REPLAY_DIR.pipeline.log"

echo "[replay] source=$VIDEO"
echo "[replay] resolution=${HIGH_WIDTH}x${HIGH_HEIGHT} ground=${GROUND_HOST}:5000 delay=${DELAY_MS}ms speed=${SPEED}x"
echo "[replay] mission=$MISSION_ID"

cleanup() {
  status=$?
  trap - EXIT INT TERM
  if [[ -n "${PIPELINE_PID:-}" ]] && kill -0 "$PIPELINE_PID" 2>/dev/null; then
    kill -INT "$PIPELINE_PID" 2>/dev/null || true
    wait "$PIPELINE_PID" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

python3 jetson/arducam_split_pipeline.py \
  --host "$GROUND_HOST" \
  --port 5000 \
  --qualification-video "$VIDEO" \
  --allow-qualification-file-source \
  --mission-id "$MISSION_ID" \
  --capture-epoch 1 \
  --high-width "$HIGH_WIDTH" \
  --high-height "$HIGH_HEIGHT" \
  --high-fps 30 \
  --network-width 960 \
  --network-height 540 \
  --network-fps 15 \
  --record-dir "$RECORD_DIR" \
  --allow-root-record-dir \
  --min-free-bytes 0 \
  --registration-url "http://${GROUND_HOST}:5001/api/v1/stream/register" \
  --ingest-token "$JETSON_INGEST_TOKEN" \
  >"$PIPELINE_LOG" 2>&1 &
PIPELINE_PID=$!

# Registration is started before the GStreamer pipeline enters PLAYING. Give
# it a short head start so the first metadata row is accepted by Ground.
sleep 0.25
kill -0 "$PIPELINE_PID" 2>/dev/null || {
  tail -80 "$PIPELINE_LOG" >&2 || true
  die "video replay pipeline exited during startup"
}

python3 jetson/replay_vision.py \
  "$EPOCH_DIR" \
  --overlay-url "http://${GROUND_HOST}:5001/api/v1/detection/overlay" \
  --token "$JETSON_INGEST_TOKEN" \
  --mission-id "$MISSION_ID" \
  --capture-epoch 1 \
  --delay-ms "$DELAY_MS" \
  --speed "$SPEED"

wait "$PIPELINE_PID"
PIPELINE_PID=
echo "[replay] completed; pipeline log=$PIPELINE_LOG"
