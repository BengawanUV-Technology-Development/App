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
import itertools
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

import cv2
import numpy as np
import requests

from coordinate_estimator import CameraCalibration, estimate_target_latlon

_LOCATED_STATUSES = {"ESTIMATED", "ESTIMATED_UNCALIBRATED"}
EARTH_RADIUS_M = 6378137.0

# Detections in the same frame whose boxes overlap this much are treated as
# the same physical target (e.g. a borderline detector threshold producing
# two boxes for one pedestrian) -- keep only the higher-confidence one.
IOU_DEDUP_THRESHOLD = 0.5

# Located detections (see _LOCATED_STATUSES) whose estimated ground position
# is within this many meters of each other, at any point across the whole
# flight, are treated as repeat sightings of the same physical target.
CLUSTER_DISTANCE_METERS = 5.0


def _iou(box_a: list[float], box_b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = inter_w * inter_h
    if intersection <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _dedup_overlapping(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Greedy NMS-style dedup for detections within a single frame. Keeps
    the higher-confidence box of each overlapping pair; two genuinely
    different targets in the same frame (non-overlapping boxes) are both
    kept untouched."""
    ordered = sorted(
        (d for d in detections if d.get("bbox_normalized_xyxy")),
        key=lambda d: float(d.get("confidence", 0)),
        reverse=True,
    )
    kept: list[dict[str, Any]] = []
    for candidate in ordered:
        box = candidate["bbox_normalized_xyxy"]
        if any(_iou(box, k["bbox_normalized_xyxy"]) >= IOU_DEDUP_THRESHOLD for k in kept):
            continue
        kept.append(candidate)
    return kept


def _flat_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat_rad = math.radians((lat1 + lat2) / 2.0)
    north_m = math.radians(lat1 - lat2) * EARTH_RADIUS_M
    east_m = math.radians(lon1 - lon2) * EARTH_RADIUS_M * math.cos(lat_rad)
    return math.hypot(north_m, east_m)


def _cluster_by_coordinate(records: list[dict[str, Any]]) -> None:
    """Union-find clustering of located detections by ground-position
    proximity, mutating each record in place with cluster_id/cluster_size/
    is_representative. This is the cross-time half of the two-stage
    dedup (the other half, _dedup_overlapping, only looks within one
    frame): the same pedestrian seen across many frames as the drone
    passes over collapses into one cluster here, and only its
    highest-confidence sighting is marked representative -- that's the pin
    the map shows by default post-flight. Detections without a location
    (coordinate status not in _LOCATED_STATUSES) can't be compared by
    position, so each is left as its own singleton cluster.
    """
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    located = [i for i, r in enumerate(records) if r["coordinate"].get("status") in _LOCATED_STATUSES]
    for position, i in enumerate(located):
        lat_i, lon_i = records[i]["coordinate"]["lat"], records[i]["coordinate"]["lon"]
        for j in located[position + 1:]:
            lat_j, lon_j = records[j]["coordinate"]["lat"], records[j]["coordinate"]["lon"]
            if _flat_distance_m(lat_i, lon_i, lat_j, lon_j) <= CLUSTER_DISTANCE_METERS:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(records)):
        groups.setdefault(find(i), []).append(i)

    for cluster_id, members in enumerate(groups.values(), start=1):
        best = max(members, key=lambda i: float(records[i]["detection"].get("confidence", 0)))
        for i in members:
            records[i]["cluster_id"] = cluster_id
            records[i]["cluster_size"] = len(members)
            records[i]["is_representative"] = i == best


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

    # Pass 1 (cheap: no video/ffmpeg access): apply the same min-interval
    # thinning as before, then within-frame IoU dedup, then compute each
    # surviving detection's coordinate. This produces the full candidate
    # set that cross-time clustering needs -- clustering can't run
    # incrementally per frame, it needs every detection's coordinate.
    candidates: list[dict[str, Any]] = []
    skipped_interval = 0
    last_seconds: float | None = None
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
        if last_seconds is not None and seconds - last_seconds < min_interval_seconds:
            skipped_interval += 1
            continue

        width, height = row.get("source_width"), row.get("source_height")
        telemetry = telemetry_by_frame.get(row.get("frame_id"))
        wrote_any = False
        for detection in _dedup_overlapping(detections):
            detection_id = detection.get("detection_id")
            if not detection_id:
                continue
            coordinate = estimate_target_latlon(
                bbox_normalized_xyxy=detection["bbox_normalized_xyxy"],
                image_width=width,
                image_height=height,
                telemetry=telemetry,
                calibration=calibration,
            )
            candidates.append({"row": row, "seconds": seconds, "detection": detection, "coordinate": coordinate})
            wrote_any = True
        if wrote_any:
            last_seconds = seconds

    _cluster_by_coordinate(candidates)

    # Pass 2: the expensive part (ffmpeg frame extraction + upload), now
    # that every candidate already knows its cluster_id/cluster_size/
    # is_representative. Grouped by frame so each frame is only extracted
    # from video.mp4 once, same as before.
    written = 0
    uploaded = 0
    with manifest_path.open("w", encoding="utf-8") as manifest_file:
        for _, frame_candidates in itertools.groupby(candidates, key=lambda c: (c["row"].get("capture_utc_ns"), c["row"].get("frame_id"))):
            frame_candidates = list(frame_candidates)
            row = frame_candidates[0]["row"]
            frame_jpeg = _extract_frame_jpeg(video_path, frame_candidates[0]["seconds"])
            if frame_jpeg is None:
                continue

            for candidate in frame_candidates:
                detection = candidate["detection"]
                bbox = detection["bbox_normalized_xyxy"]
                label = f"{detection.get('class', '?')} {float(detection.get('confidence', 0)):.2f}"
                snapshot_jpeg = _draw_bbox(frame_jpeg, bbox, label)
                detection_id = detection["detection_id"]
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
                    "coordinate": candidate["coordinate"],
                    "cluster_id": candidate["cluster_id"],
                    "cluster_size": candidate["cluster_size"],
                    "is_representative": candidate["is_representative"],
                }
                manifest_file.write(json.dumps(
                    {**record, "snapshot_file": f"snapshots/{snapshot_filename}"}, separators=(",", ":"),
                ) + "\n")
                written += 1
                if upload_session is not None and _send_to_ground(upload_session, ground_url, ingest_token, record, snapshot_jpeg):
                    uploaded += 1

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
