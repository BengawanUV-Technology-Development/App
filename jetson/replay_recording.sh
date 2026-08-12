#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  jetson/replay_recording.sh SOURCE [options]

SOURCE may be an epoch directory or a standalone video file. A standalone
video runs video-only unless --inference or --metadata-epoch is supplied.

Options:
  --delay-ms N       Artificial metadata delay; default 0
  --speed N          Replay speed multiplier; default 1
  --ground-host IP   Ground laptop Tailscale IP; default 100.114.81.87
  --inference        Run the configured YOLO model and publish live overlay
  --high-width N     Override inference/recording width
  --high-height N    Override inference/recording height
  --metadata-epoch DIR
                     Optional epoch directory containing detections.jsonl
  --record-dir DIR   Temporary output directory; default /tmp/buv-replay
  --env-file FILE    Root environment file; default /etc/buv/jetson-recording-v03.env
  -h, --help         Show this help

An epoch directory must contain video.mp4 and detections.jsonl.
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
SOURCE=""
METADATA_EPOCH=""
RUN_INFERENCE=false
HIGH_WIDTH_OVERRIDE=""
HIGH_HEIGHT_OVERRIDE=""
DELAY_MS=0
SPEED=1
GROUND_HOST=${REPLAY_GROUND_HOST:-100.114.81.87}
RECORD_DIR=${REPLAY_RECORD_DIR:-/tmp/buv-replay}
ENV_FILE=${JETSON_REPLAY_ENV_FILE:-/etc/buv/jetson-recording-v03.env}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --video)
      [[ $# -ge 2 ]] || die "--video requires a file path"
      SOURCE=$2
      shift 2
      ;;
    --metadata-epoch)
      [[ $# -ge 2 ]] || die "--metadata-epoch requires a directory"
      METADATA_EPOCH=$2
      shift 2
      ;;
    --inference)
      RUN_INFERENCE=true
      shift
      ;;
    --high-width)
      [[ $# -ge 2 ]] || die "--high-width requires a value"
      HIGH_WIDTH_OVERRIDE=$2
      shift 2
      ;;
    --high-height)
      [[ $# -ge 2 ]] || die "--high-height requires a value"
      HIGH_HEIGHT_OVERRIDE=$2
      shift 2
      ;;
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
      [[ -z "$SOURCE" ]] || die "unexpected argument: $1"
      SOURCE=$1
      shift
      ;;
  esac
done

[[ -n "$SOURCE" ]] || { usage >&2; exit 2; }
[[ "$RUN_INFERENCE" != true || -z "$METADATA_EPOCH" ]] || die "use either --inference or --metadata-epoch, not both"
SOURCE=$(realpath "$SOURCE")
if [[ -d "$SOURCE" ]]; then
  EPOCH_DIR="$SOURCE"
  VIDEO="$EPOCH_DIR/video.mp4"
  [[ -z "$METADATA_EPOCH" ]] || die "--metadata-epoch is unnecessary with an epoch directory"
  METADATA_EPOCH="$EPOCH_DIR"
else
  [[ -f "$SOURCE" ]] || die "source does not exist: $SOURCE"
  VIDEO="$SOURCE"
  if [[ -n "$METADATA_EPOCH" ]]; then
    METADATA_EPOCH=$(realpath "$METADATA_EPOCH")
  fi
fi

if [[ -n "$METADATA_EPOCH" ]]; then
  DETECTIONS="$METADATA_EPOCH/detections.jsonl"
  [[ -f "$DETECTIONS" ]] || die "detections.jsonl not found in $METADATA_EPOCH"
fi

read_env_value() {
  local name=$1
  local value=${!name:-}
  if [[ -z "$value" ]]; then
    [[ -f "$ENV_FILE" ]] || die "environment file not found: $ENV_FILE"
    value=$(sudo awk -F= -v key="$name" \
      '$1==key{print substr($0,index($0,"=")+1); exit}' \
      "$ENV_FILE" | tr -d '\r')
  fi
  printf '%s' "$value"
}

# systemd receives secrets from a root-only EnvironmentFile. Load only the
# values needed here and never print them or write them to a log.
JETSON_INGEST_TOKEN=$(read_env_value JETSON_INGEST_TOKEN)
export JETSON_INGEST_TOKEN
[[ -n "$JETSON_INGEST_TOKEN" ]] || die "JETSON_INGEST_TOKEN is empty"
if [[ "$RUN_INFERENCE" == true ]]; then
  MODEL_WEIGHTS=$(read_env_value JETSON_MODEL_WEIGHTS)
  MODEL_MANIFEST=$(read_env_value JETSON_MODEL_MANIFEST)
  MODEL_DEVICE=$(read_env_value JETSON_MODEL_DEVICE)
  MODEL_IMGSZ=$(read_env_value JETSON_MODEL_IMGSZ)
  MODEL_CONF=$(read_env_value JETSON_MODEL_CONF)
  MODEL_SAHI=$(read_env_value JETSON_MODEL_SAHI)
  [[ -n "$MODEL_WEIGHTS" ]] || die "JETSON_MODEL_WEIGHTS is empty"
  [[ -f "$MODEL_WEIGHTS" ]] || die "model weights not found: $MODEL_WEIGHTS"
  [[ -f "$MODEL_MANIFEST" ]] || die "model manifest not found: $MODEL_MANIFEST"
fi

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
if [[ -n "$HIGH_WIDTH_OVERRIDE" || -n "$HIGH_HEIGHT_OVERRIDE" ]]; then
  [[ -n "$HIGH_WIDTH_OVERRIDE" && -n "$HIGH_HEIGHT_OVERRIDE" ]] || die "--high-width and --high-height must be used together"
  HIGH_WIDTH=$HIGH_WIDTH_OVERRIDE
  HIGH_HEIGHT=$HIGH_HEIGHT_OVERRIDE
fi

MISSION_ID="mission-$(python3 -c 'import uuid; print(uuid.uuid4())')"
REPLAY_DIR="$RECORD_DIR/$MISSION_ID"
mkdir -p "$RECORD_DIR"
PIPELINE_LOG="$REPLAY_DIR.pipeline.log"

echo "[replay] source=$VIDEO"
echo "[replay] resolution=${HIGH_WIDTH}x${HIGH_HEIGHT} ground=${GROUND_HOST}:5000 delay=${DELAY_MS}ms speed=${SPEED}x"
echo "[replay] mission=$MISSION_ID"
if [[ -n "$METADATA_EPOCH" ]]; then
  echo "[replay] metadata=$METADATA_EPOCH"
else
  echo "[replay] metadata=disabled (video-only)"
fi
if [[ "$RUN_INFERENCE" == true ]]; then
  echo "[replay] inference=enabled model=$MODEL_WEIGHTS device=$MODEL_DEVICE imgsz=$MODEL_IMGSZ conf=$MODEL_CONF sahi=$MODEL_SAHI"
fi

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

PIPELINE_ARGS=(
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
  --ingest-token "$JETSON_INGEST_TOKEN"
)
if [[ "$RUN_INFERENCE" == true ]]; then
  PIPELINE_ARGS+=(
    --weights "$MODEL_WEIGHTS"
    --model-manifest "$MODEL_MANIFEST"
    --device "$MODEL_DEVICE"
    --imgsz "$MODEL_IMGSZ"
    --conf "$MODEL_CONF"
    --ingest-url "http://${GROUND_HOST}:5001/api/v1/detection/overlay"
  )
  if [[ "$MODEL_SAHI" == true ]]; then
    PIPELINE_ARGS+=(--sahi)
  fi
fi
"${PIPELINE_ARGS[@]}" >"$PIPELINE_LOG" 2>&1 &
PIPELINE_PID=$!

# Registration is started before the GStreamer pipeline enters PLAYING. Give
# it a short head start so the first metadata row is accepted by Ground.
sleep 0.25
kill -0 "$PIPELINE_PID" 2>/dev/null || {
  tail -80 "$PIPELINE_LOG" >&2 || true
  die "video replay pipeline exited during startup"
}

if [[ "$RUN_INFERENCE" == true ]]; then
  echo "[replay] running live YOLO inference; overlay is published by the pipeline"
  wait "$PIPELINE_PID"
  PIPELINE_PID=
  echo "[replay] completed; pipeline log=$PIPELINE_LOG"
  exit 0
elif [[ -n "$METADATA_EPOCH" ]]; then
  python3 jetson/replay_vision.py \
    "$METADATA_EPOCH" \
    --overlay-url "http://${GROUND_HOST}:5001/api/v1/detection/overlay" \
    --token "$JETSON_INGEST_TOKEN" \
    --mission-id "$MISSION_ID" \
    --capture-epoch 1 \
    --delay-ms "$DELAY_MS" \
    --speed "$SPEED"
else
  echo "[replay] running video-only; no bbox metadata will be published"
  wait "$PIPELINE_PID"
  PIPELINE_PID=
  echo "[replay] completed; pipeline log=$PIPELINE_LOG"
  exit 0
fi

wait "$PIPELINE_PID"
PIPELINE_PID=
echo "[replay] completed; pipeline log=$PIPELINE_LOG"
