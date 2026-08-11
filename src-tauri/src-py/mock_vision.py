"""Generate a deterministic synthetic vision stream for local pipeline testing.

The script does not run an object-detection model. It draws a moving synthetic
person box on an arbitrary input video, or on generated frames when no video is
available. It writes an annotated video and one JSON record per frame.

Example:
    python mock_vision.py --video ../../../Coordinate-Estimator/input_rendered.mp4

The optional --post-first flag sends only the first authenticated schema-v2
event to the persistent ingest route. Coordinates remain ``not_available``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from urllib import request
import uuid

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - environment-specific message
    raise SystemExit("opencv-python and numpy are required to run mock_vision.py") from exc


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VIDEO = REPO_ROOT / "Coordinate-Estimator" / "input_rendered.mp4"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "runtime" / "mock_vision" / "output_annotated.mp4"
DEFAULT_METADATA = Path(__file__).resolve().parent / "runtime" / "mock_vision" / "detections.jsonl"
MISSION_ID = "mission-00000000-0000-0000-0000-000000000098"


def parse_args():
    parser = argparse.ArgumentParser(description="Generate synthetic schema-v2 bounding boxes")
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO, help="Input video; omitted/unavailable means synthetic frames")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Annotated output video")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA, help="Per-frame detection JSONL")
    parser.add_argument("--frames", type=int, default=120, help="Maximum frames; 0 means all source frames")
    parser.add_argument("--fps", type=float, default=25.0, help="FPS for synthetic frames or invalid source FPS")
    parser.add_argument("--width", type=int, default=1280, help="Synthetic frame width")
    parser.add_argument("--height", type=int, default=720, help="Synthetic frame height")
    parser.add_argument("--post-first", metavar="URL", help="POST only the first dummy detection to this endpoint")
    parser.add_argument("--ingest-token", default=os.getenv("JETSON_INGEST_TOKEN", ""))
    parser.add_argument("--show", action="store_true", help="Show the annotated stream in an OpenCV window")
    return parser.parse_args()


def clamp(value, low, high):
    return max(low, min(high, value))


def dummy_detection(frame_id, width, height, fps):
    # A deterministic path makes replay comparisons easy and avoids random test failures.
    center_x = width * (0.50 + 0.20 * math.sin(frame_id / 18.0))
    center_y = height * (0.52 + 0.06 * math.cos(frame_id / 23.0))
    box_width = max(40, int(width * 0.12))
    box_height = max(60, int(height * 0.28))
    x1 = int(clamp(center_x - box_width / 2, 0, width - 1))
    y1 = int(clamp(center_y - box_height / 2, 0, height - 1))
    x2 = int(clamp(x1 + box_width, x1 + 1, width - 1))
    y2 = int(clamp(y1 + box_height, y1 + 1, height - 1))
    return {
        "track_id": "sim-person-001",
        "class": "person",
        "confidence": 0.92,
        "bbox_px": [x1, y1, x2, y2],
        "bbox_norm": [x1 / width, y1 / height, x2 / width, y2 / height],
        "coordinate": {"status": "not_available"},
        "frame_time_seconds": frame_id / fps if fps > 0 else 0.0,
    }


def synthetic_frame(frame_id, width, height):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (18, 28, 31)
    for x in range(0, width, 80):
        cv2.line(frame, (x, 0), (x, height), (30, 52, 54), 1)
    for y in range(0, height, 80):
        cv2.line(frame, (0, y), (width, y), (30, 52, 54), 1)
    cv2.putText(frame, "SYNTHETIC CAMERA SOURCE", (28, 54), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (110, 220, 205), 2)
    cv2.putText(frame, f"Frame {frame_id:04d}", (28, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 220, 220), 2)
    return frame


def post_json(url, payload, token):
    encoded = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=encoded, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    })
    with request.urlopen(req, timeout=10) as response:
        return response.status, response.read().decode("utf-8")


def main():
    args = parse_args()
    capture = cv2.VideoCapture(str(args.video)) if args.video.exists() else None
    source_is_video = bool(capture and capture.isOpened())
    if not source_is_video and capture is not None:
        capture.release()

    if source_is_video:
        source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        fps = source_fps if 1 <= source_fps <= 120 else args.fps
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or args.width)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or args.height)
        source_description = str(args.video)
        source_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        limit = min(args.frames, source_frame_count) if args.frames > 0 and source_frame_count > 0 else args.frames
    else:
        fps = args.fps
        width = args.width
        height = args.height
        source_description = "synthetic"
        limit = args.frames if args.frames > 0 else 120

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(args.output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise SystemExit(f"Cannot create output video: {args.output}")

    posted = False
    processed = 0
    with args.metadata.open("w", encoding="utf-8") as metadata_file:
        while limit <= 0 or processed < limit:
            if source_is_video:
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))
            else:
                frame = synthetic_frame(processed, width, height)

            detection = dummy_detection(processed, width, height, fps)
            x1, y1, x2, y2 = detection["bbox_px"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 230, 170), 3)
            cv2.putText(
                frame,
                "SIMULATED person 0.92 | track sim-person-001",
                (x1, max(28, y1 - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 230, 170),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                frame,
                "COORDINATE NOT AVAILABLE",
                (24, height - 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 220, 255),
                2,
                cv2.LINE_AA,
            )
            writer.write(frame)

            payload = {
                "schema_version": "2.0",
                "type": "vision.detection_event",
                "mission_id": MISSION_ID,
                "capture_epoch": 1,
                "frame_id": processed,
                "camera_id": "arducam",
                "capture_utc_ns": time.time_ns(),
                "capture_monotonic_ns": time.monotonic_ns(),
                "source_pts_ns": int(processed * 1_000_000_000 / fps),
                "detection_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"buv-mock-vision-{processed}")),
                "class": detection["class"],
                "confidence": detection["confidence"],
                "bbox_normalized_xyxy": detection["bbox_norm"],
                "coordinate": {"status": "not_available"},
            }
            metadata_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

            if args.post_first and not posted:
                try:
                    if not args.ingest_token:
                        raise RuntimeError("--ingest-token or JETSON_INGEST_TOKEN is required")
                    status, response = post_json(args.post_first, payload, args.ingest_token)
                    print(f"Posted first simulated detection: HTTP {status} {response[:200]}")
                except Exception as exc:
                    print(f"Could not post simulated detection: {exc}")
                posted = True

            processed += 1
            if args.show:
                cv2.imshow("Mock Vision", frame)
                if cv2.waitKey(max(1, int(1000 / max(fps, 1))) & 0xFF) == ord("q"):
                    break

    writer.release()
    if capture is not None:
        capture.release()
    if args.show:
        cv2.destroyAllWindows()

    print(f"Generated {processed} frames from {source_description}")
    print(f"Annotated video: {args.output}")
    print(f"Detection metadata: {args.metadata}")


if __name__ == "__main__":
    main()
