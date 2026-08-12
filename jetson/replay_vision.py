#!/usr/bin/env python3
"""Replay recorded detection metadata to the Ground overlay endpoint.

This tool is for deterministic qualification only. Pair it with
``arducam_split_pipeline.py --qualification-video`` running in capture-only
mode. The video replay supplies RTP preview frames while this process replays
the recorded ``detections.jsonl`` rows using the same canonical frame IDs.

The optional delay is applied only to metadata publication. It makes the
Ground ``FrameSynchronizer`` behavior observable without requiring an
Arducam, detector, or live vehicle.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ReplayError(ValueError):
    """Raised when replay input or configuration is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"cannot read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReplayError(f"JSON file must contain an object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReplayError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ReplayError(f"JSONL row must be an object at {path}:{line_number}")
                rows.append(payload)
    except OSError as exc:
        raise ReplayError(f"cannot read JSONL file {path}: {exc}") from exc
    return rows


def _identity(payload: dict[str, Any]) -> tuple[str, int, int, str]:
    try:
        identity = (
            str(payload["mission_id"]),
            int(payload["capture_epoch"]),
            int(payload["frame_id"]),
            str(payload["camera_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayError("detection row is missing canonical frame identity") from exc
    if not identity[0].startswith("mission-") or identity[1] < 1 or identity[2] < 0:
        raise ReplayError(f"invalid canonical frame identity: {identity}")
    if identity[3] != "arducam":
        raise ReplayError(f"unsupported camera identity: {identity[3]}")
    return identity


def _load_frame_times(session_dir: Path, fallback_fps: float) -> dict[int, float]:
    path = session_dir / "frames.jsonl"
    if not path.is_file():
        return {}
    rows = _read_jsonl(path)
    timestamps: dict[int, float] = {}
    first_timestamp: int | None = None
    for row in rows:
        try:
            frame_id = int(row["frame_id"])
            timestamp_ns = int(row["capture_monotonic_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        if first_timestamp is None:
            first_timestamp = timestamp_ns
        timestamps[frame_id] = max(0.0, (timestamp_ns - first_timestamp) / 1_000_000_000)
    if timestamps:
        return timestamps
    return {frame_id: frame_id / fallback_fps for frame_id in range(len(rows))}


def _rewrite_identity(
    payload: dict[str, Any],
    *,
    mission_id: str | None,
    capture_epoch: int | None,
) -> dict[str, Any]:
    result = dict(payload)
    if mission_id is not None:
        result["mission_id"] = mission_id
    if capture_epoch is not None:
        result["capture_epoch"] = capture_epoch
    _identity(result)
    return result


def _event_payloads(frame_payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    base = {
        key: frame_payload[key]
        for key in ("schema_version", "mission_id", "capture_epoch", "frame_id", "camera_id")
    }
    for detection in frame_payload.get("detections", []):
        if not isinstance(detection, dict):
            continue
        if not detection.get("detection_id"):
            continue
        yield {
            **base,
            "type": "vision.detection_event",
            "detection_id": detection["detection_id"],
            "class": detection.get("class"),
            "confidence": detection.get("confidence"),
            "bbox_normalized_xyxy": detection.get("bbox_normalized_xyxy"),
            "coordinate": {"status": "not_available"},
        }


def _post(url: str, token: str, payload: dict[str, Any], timeout: float) -> None:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status >= 300:
                raise ReplayError(f"HTTP {response.status} from {url}")
    except HTTPError as exc:
        raise ReplayError(f"HTTP {exc.code} from {url}: {exc.reason}") from exc
    except URLError as exc:
        raise ReplayError(f"cannot reach {url}: {exc.reason}") from exc


def replay(args: argparse.Namespace) -> dict[str, int]:
    session_dir = args.session_dir.expanduser().resolve()
    detections_path = session_dir / "detections.jsonl"
    if not detections_path.is_file():
        raise ReplayError(f"missing detection sidecar: {detections_path}")
    if args.delay_ms < 0 or args.start_delay_ms < 0:
        raise ReplayError("delay values must not be negative")
    if args.speed <= 0:
        raise ReplayError("speed must be greater than zero")
    if args.fps <= 0:
        raise ReplayError("fps must be greater than zero")

    epoch = _read_json(session_dir / "epoch.json") if (session_dir / "epoch.json").is_file() else {}
    default_mission = str(epoch.get("mission_id") or "")
    default_epoch = epoch.get("capture_epoch")
    rows = _read_jsonl(detections_path)
    frame_times = _load_frame_times(session_dir, args.fps)
    if not rows:
        raise ReplayError(f"detection sidecar is empty: {detections_path}")

    mission_id = args.mission_id or default_mission or str(rows[0].get("mission_id") or "")
    capture_epoch = args.capture_epoch or int(default_epoch or rows[0].get("capture_epoch") or 1)
    if not mission_id:
        raise ReplayError("mission ID is unavailable; provide --mission-id")

    selected: list[dict[str, Any]] = []
    for row in rows:
        rewritten = _rewrite_identity(
            row,
            mission_id=mission_id,
            capture_epoch=capture_epoch,
        )
        frame_id = int(rewritten["frame_id"])
        if frame_id < args.start_frame or (args.end_frame is not None and frame_id > args.end_frame):
            continue
        selected.append(rewritten)
    if not selected:
        raise ReplayError("no detection rows matched the selected frame range")

    started = time.monotonic() + args.start_delay_ms / 1000.0
    sent_overlay = 0
    sent_events = 0
    for payload in selected:
        frame_id = int(payload["frame_id"])
        offset = frame_times.get(frame_id, frame_id / args.fps)
        target = started + (offset / args.speed) + args.delay_ms / 1000.0
        remaining = target - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        if not args.dry_run:
            _post(args.overlay_url, args.token, payload, args.timeout)
            sent_overlay += 1
            if args.event_url:
                for event in _event_payloads(payload):
                    _post(args.event_url, args.token, event, args.timeout)
                    sent_events += 1
        else:
            sent_overlay += 1
            sent_events += sum(1 for _ in _event_payloads(payload)) if args.event_url else 0

    return {"rows_selected": len(selected), "overlay_sent": sent_overlay, "events_sent": sent_events}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path, help="Epoch directory containing detections.jsonl")
    parser.add_argument("--overlay-url", required=True, help="Ground /api/v1/detection/overlay URL")
    parser.add_argument("--event-url", help="Optional Ground /api/v1/detection/ingest URL")
    parser.add_argument("--token", required=True, help="Ground ingest bearer token")
    parser.add_argument("--delay-ms", type=float, default=0.0, help="Artificial metadata delay")
    parser.add_argument("--start-delay-ms", type=float, default=0.0, help="Delay before replay clock starts")
    parser.add_argument("--speed", type=float, default=1.0, help="Replay speed multiplier")
    parser.add_argument("--fps", type=float, default=30.0, help="Fallback source FPS")
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--end-frame", type=int)
    parser.add_argument("--mission-id", help="Override mission ID to match the video replay")
    parser.add_argument("--capture-epoch", type=int, help="Override capture epoch to match the video replay")
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true", help="Validate and pace without HTTP requests")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        stats = replay(parse_args(argv))
    except ReplayError as exc:
        print(f"[replay] ERROR: {exc}")
        return 2
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
