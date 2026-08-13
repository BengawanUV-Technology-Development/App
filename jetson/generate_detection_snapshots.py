#!/usr/bin/env python3
"""Post-flight: generate low-res bbox snapshot images + a coordinate
manifest for one recorded epoch.

Runs on the Jetson after a recording stops (see recording_agent.py's
stop(), which spawns this in the background) or manually against any past
epoch directory. See docs/post-flight-detection-snapshots.md for the full
design discussion -- in short: the live feed is real-time now and never
holds a video frame waiting for its detection, so a detection that misses
that live opportunistic window is reviewed here instead, after landing,
by seeking the already-recorded video.mp4 rather than needing anything to
have been cached while the frame was live.

Usage:
  jetson/generate_detection_snapshots.py EPOCH_DIR [--min-interval-seconds N]

EPOCH_DIR must contain video.mp4, detections.jsonl and (optionally, for
coordinate estimation) telemetry.jsonl -- the layout every recording
already produces (see SplitPipeline in arducam_split_pipeline.py).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

import cv2
import numpy as np
import requests

from coordinate_estimator import CameraCalibration, estimate_target_latlon


def _load_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _load_telemetry_by_frame_id(telemetry_path: Path) -> dict[int, dict[str, Any]]:
    by_frame: dict[int, dict[str, Any]] = {}
    for row in _load_jsonl(telemetry_path):
        frame_id = row.get("frame_id")
        telemetry = row.get("telemetry")
        if frame_id is not None and isinstance(telemetry, dict):
            by_frame[frame_id] = telemetry
    return by_frame


def _extract_frame_jpeg(video_path: Path, seconds: float) -> bytes | None:
    """Extract one JPEG at `seconds` into video_path.

    -ss *before* -i seeks to the input's nearest preceding keyframe first
    (fast) and only decodes forward from there to the target, instead of
    decoding the whole file from zero every time (which was measured to
    make a batch of a few hundred extractions take minutes-to-effectively-
    forever on a long recording). Record-branch keyframes are spaced
    ~1s apart (key_int_max in arducam_split_pipeline.py), so this is
    accurate to at most that -- fine for a hover preview, not for
    frame-exact evidence (which is what detections.jsonl + video.mp4
    remain for)."""

    seconds = max(0.0, seconds)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-loglevel", "error",
                "-ss", f"{seconds:.3f}",
                "-i", str(video_path),
                "-frames:v", "1",
                "-f", "image2pipe", "-vcodec", "mjpeg",
                "-",
            ],
            capture_output=True,
            timeout=15,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"[snapshot] ffmpeg extraction failed at {seconds:.3f}s: {exc}", file=sys.stderr, flush=True)
        return None
    return result.stdout or None


SNAPSHOT_MAX_WIDTH = 960  # matches JETSON_VIDEO_PREVIEW_WIDTH -- this is a
# hover-preview convenience, not the evidentiary artifact (that stays in
# the full-res video.mp4), so it doesn't need to be any bigger.


def _draw_bbox(jpeg_bytes: bytes, bbox_normalized_xyxy: list[float], label: str) -> bytes:
    array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        return jpeg_bytes
    height, width = image.shape[:2]
    if width > SNAPSHOT_MAX_WIDTH:
        scale = SNAPSHOT_MAX_WIDTH / width
        image = cv2.resize(image, (SNAPSHOT_MAX_WIDTH, round(height * scale)), interpolation=cv2.INTER_AREA)
        height, width = image.shape[:2]
    x1 = int(max(0.0, min(1.0, bbox_normalized_xyxy[0])) * width)
    y1 = int(max(0.0, min(1.0, bbox_normalized_xyxy[1])) * height)
    x2 = int(max(0.0, min(1.0, bbox_normalized_xyxy[2])) * width)
    y2 = int(max(0.0, min(1.0, bbox_normalized_xyxy[3])) * height)
    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 220, 0), 2)
    cv2.putText(
        image, label, (x1, max(0, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 0), 1, cv2.LINE_AA,
    )
    success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return encoded.tobytes() if success else jpeg_bytes


def _default_ground_url() -> str | None:
    host = os.getenv("JETSON_GCS_HOST", "").strip()
    if not host:
        return None
    port = os.getenv("JETSON_GCS_API_PORT", "5001").strip()
    return f"http://{host}:{port}/api/v1/postflight/detections"


def _send_to_ground(
    session: requests.Session, ground_url: str, token: str, record: dict[str, Any], snapshot_jpeg: bytes,
) -> bool:
    payload = {**record, "snapshot_jpeg_base64": base64.b64encode(snapshot_jpeg).decode("ascii")}
    try:
        response = session.post(
            ground_url, json=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if response.status_code >= 300:
            print(f"[snapshot] ground rejected {record['detection_id']}: HTTP {response.status_code} {response.text[:200]}", file=sys.stderr, flush=True)
            return False
        return True
    except requests.RequestException as exc:
        print(f"[snapshot] failed to send {record['detection_id']} to ground: {exc}", file=sys.stderr, flush=True)
        return False


def generate(
    epoch_dir: Path, min_interval_seconds: float, *, ground_url: str | None = None, ingest_token: str | None = None,
) -> Path:
    detections_path = epoch_dir / "detections.jsonl"
    telemetry_path = epoch_dir / "telemetry.jsonl"
    video_path = epoch_dir / "video.mp4"
    if not detections_path.is_file() or not video_path.is_file():
        raise SystemExit(f"missing detections.jsonl or video.mp4 under {epoch_dir}")

    output_dir = epoch_dir / "postflight"
    snapshots_dir = output_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.jsonl"

    telemetry_by_frame = _load_telemetry_by_frame_id(telemetry_path)
    calibration = CameraCalibration()
    upload_session = requests.Session() if (ground_url and ingest_token) else None
    if (ground_url and not ingest_token) or (ingest_token and not ground_url):
        print("[snapshot] both --ground-url and --ingest-token are required to upload; skipping upload", file=sys.stderr, flush=True)

    written = 0
    uploaded = 0
    skipped_interval = 0
    last_written_seconds: float | None = None
    with manifest_path.open("w", encoding="utf-8") as manifest_file:
        for row in _load_jsonl(detections_path):
            detections = row.get("detections") or []
            if not detections:
                continue
            source_pts_ns = row.get("source_pts_ns")
            if source_pts_ns is None:
                continue
            seconds = source_pts_ns / 1_000_000_000
            # A sustained detection streak would otherwise produce a nearly
            # identical crop every ~1/inference_fps seconds; thin those out.
            if last_written_seconds is not None and seconds - last_written_seconds < min_interval_seconds:
                skipped_interval += 1
                continue

            width, height = row.get("source_width"), row.get("source_height")
            frame_jpeg = _extract_frame_jpeg(video_path, seconds)
            if frame_jpeg is None:
                continue

            telemetry = telemetry_by_frame.get(row.get("frame_id"))
            wrote_any = False
            for detection in detections:
                bbox = detection.get("bbox_normalized_xyxy")
                if not bbox:
                    continue
                coordinate = estimate_target_latlon(
                    bbox_normalized_xyxy=bbox,
                    image_width=width,
                    image_height=height,
                    telemetry=telemetry,
                    calibration=calibration,
                )
                label = f"{detection.get('class', '?')} {float(detection.get('confidence', 0)):.2f}"
                snapshot_jpeg = _draw_bbox(frame_jpeg, bbox, label)
                detection_id = detection.get("detection_id")
                if not detection_id:
                    continue
                snapshot_filename = f"{detection_id}.jpg"
                (snapshots_dir / snapshot_filename).write_bytes(snapshot_jpeg)
                record = {
                    "detection_id": detection_id,
                    "mission_id": row.get("mission_id"),
                    "capture_epoch": row.get("capture_epoch"),
                    "frame_id": row.get("frame_id"),
                    "capture_utc_ns": row.get("capture_utc_ns"),
                    "class": detection.get("class"),
                    "confidence": detection.get("confidence"),
                    "bbox_normalized_xyxy": bbox,
                    "coordinate": coordinate,
                }
                manifest_file.write(json.dumps(
                    {**record, "snapshot_file": f"snapshots/{snapshot_filename}"}, separators=(",", ":"),
                ) + "\n")
                written += 1
                wrote_any = True
                if upload_session is not None and _send_to_ground(upload_session, ground_url, ingest_token, record, snapshot_jpeg):
                    uploaded += 1
            if wrote_any:
                last_written_seconds = seconds

    print(
        f"[snapshot] wrote {written} detection snapshot(s) ({uploaded} uploaded to ground), "
        f"skipped {skipped_interval} by min-interval, manifest={manifest_path}",
        flush=True,
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("epoch_dir", type=Path, help="Recorded epoch directory (contains video.mp4, detections.jsonl)")
    parser.add_argument(
        "--min-interval-seconds", type=float, default=2.0,
        help="Skip generating a new snapshot until at least this much video time has passed since the last one (default 2.0)",
    )
    parser.add_argument(
        "--ground-url", default=None,
        help="POST target for each snapshot (default: derived from JETSON_GCS_HOST/JETSON_GCS_API_PORT, "
        "same as the live pipeline's other ground endpoints)",
    )
    parser.add_argument(
        "--ingest-token", default=None,
        help="Bearer token for --ground-url (default: JETSON_INGEST_TOKEN env var)",
    )
    parser.add_argument(
        "--no-upload", action="store_true",
        help="Generate the manifest+snapshots locally only, never attempt to send them to ground",
    )
    args = parser.parse_args()
    ground_url = None if args.no_upload else (args.ground_url or _default_ground_url())
    ingest_token = None if args.no_upload else (args.ingest_token or os.getenv("JETSON_INGEST_TOKEN", "").strip() or None)
    generate(args.epoch_dir.resolve(), args.min_interval_seconds, ground_url=ground_url, ingest_token=ingest_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
