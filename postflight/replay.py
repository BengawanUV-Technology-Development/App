"""Replay recorded frames with source-time-interpolated telemetry.

This is a post-flight, receive-only replay helper.  It uses the same frame
identity and source-time interpolation path as the synchronization tool:

    video frame N -> frames.jsonl frame_id N -> capture_utc_ns
        -> source_time_valid telemetry -> interpolated UAV state

It does not open MAVLink, publish UDP packets, send commands, or modify the
source video, frame metadata, or telemetry files.  With ``--video`` it also
checks that the recorded video has exactly one readable frame per metadata
record and no trailing frames.  Without ``--video`` it still validates the
complete frame/telemetry timeline, which is useful when the large video stays
on Jetson.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from jetson.frame_metadata import FrameMetadataValidationError, validate_frame_metadata
from postflight.synchronization import (
    SynchronizationError,
    interpolate_telemetry,
    load_frame_index,
    load_telemetry_timeline,
)


REPLAY_RECORD_SCHEMA_VERSION = 1
_REQUIRED_STATE_FIELDS = (
    "latitude",
    "longitude",
    "altitude",
    "roll_deg",
    "pitch_deg",
    "yaw_deg",
)


class ReplayError(RuntimeError):
    """Raised when a replay cannot preserve frame/telemetry identity."""


def build_replay_record(
    frame: dict[str, Any],
    telemetry: dict[str, Any],
    video_frame_index: int,
    *,
    video_width: int | None = None,
    video_height: int | None = None,
) -> dict[str, Any]:
    """Build one auditable replay event from an exact frame and state."""

    if not isinstance(video_frame_index, int) or video_frame_index < 0:
        raise ReplayError("video_frame_index must be a non-negative integer")
    mission_id = frame.get("mission_id")
    frame_id = frame.get("frame_id")
    capture_utc_ns = frame.get("capture_utc_ns")
    if not isinstance(mission_id, str) or not isinstance(frame_id, int):
        raise ReplayError("frame identity is incomplete")
    if not isinstance(capture_utc_ns, int) or capture_utc_ns <= 0:
        raise ReplayError(f"frame {frame_id} has invalid capture_utc_ns")
    missing = [field for field in _REQUIRED_STATE_FIELDS if telemetry.get(field) is None]
    if missing:
        raise ReplayError(
            f"telemetry state is incomplete at frame {frame_id}: {', '.join(missing)}"
        )

    return {
        "schema_version": REPLAY_RECORD_SCHEMA_VERSION,
        "record_type": "replay_frame",
        "mission_id": mission_id,
        "capture_epoch": frame.get("capture_epoch"),
        "frame_id": frame_id,
        "camera_id": frame.get("camera_id"),
        "capture_utc_ns": capture_utc_ns,
        "source_pts_ns": frame.get("source_pts_ns"),
        "video_frame_index": video_frame_index,
        "video_width": video_width,
        "video_height": video_height,
        "telemetry_sync_status": "synchronized",
        "telemetry": telemetry,
    }


def build_replay_records(
    frames_path: str | Path,
    telemetry_path: str | Path,
    *,
    expected_mission_id: str | None = None,
) -> list[dict[str, Any]]:
    """Validate every frame against the source-time telemetry timeline.

    This metadata-only mode deliberately does not open the video.  It is safe
    to run on Ground while the high-resolution source remains on Jetson.
    """

    frame_index = _load_validated_frame_index(
        frames_path,
        expected_mission_id=expected_mission_id,
    )
    frame_ids = sorted(frame_index)
    mission_id = frame_index[frame_ids[0]]["mission_id"]
    timeline = load_telemetry_timeline(telemetry_path, mission_id)
    records: list[dict[str, Any]] = []
    for video_frame_index, frame_id in enumerate(frame_ids):
        frame = frame_index[frame_id]
        try:
            telemetry = interpolate_telemetry(timeline, frame["capture_utc_ns"])
            records.append(
                build_replay_record(frame, telemetry, video_frame_index)
            )
        except (KeyError, SynchronizationError, ReplayError) as exc:
            raise ReplayError(f"cannot replay frame_id {frame_id}: {exc}") from exc
    return records


def replay_mission(
    frames_path: str | Path,
    telemetry_path: str | Path,
    output_path: str | Path,
    *,
    video_path: str | Path | None = None,
    expected_mission_id: str | None = None,
    speed: float = 1.0,
    realtime: bool = True,
    overwrite: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Replay a mission and write one synchronized event per frame.

    ``speed=1.0`` follows the recorded UTC capture intervals.  Tests can set
    ``realtime=False`` so no wall-clock sleep is performed.
    """

    if speed <= 0:
        raise ReplayError("speed must be greater than zero")
    output = Path(output_path)
    if output.exists() and not overwrite:
        raise ReplayError(f"refusing to overwrite replay file: {output}")

    frame_index = _load_validated_frame_index(
        frames_path,
        expected_mission_id=expected_mission_id,
    )
    frame_ids = sorted(frame_index)
    mission_id = frame_index[frame_ids[0]]["mission_id"]
    timeline = load_telemetry_timeline(telemetry_path, mission_id)
    capture = None
    video_checked = video_path is not None
    if video_path is not None:
        video = Path(video_path)
        if not video.is_file() or video.stat().st_size <= 0:
            raise ReplayError(f"video is missing or empty: {video}")
        try:
            import cv2
        except ImportError as exc:
            raise ReplayError("video replay requires opencv-python") from exc
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise ReplayError(f"cannot open recorded video: {video}")

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and overwrite:
        output.unlink()
    handle = output.open("x", encoding="utf-8")
    first_capture_ns = frame_index[frame_ids[0]]["capture_utc_ns"]
    replay_started = monotonic_fn()
    frames_processed = 0
    complete_states = 0
    try:
        for video_frame_index, frame_id in enumerate(frame_ids):
            frame = frame_index[frame_id]
            video_width = None
            video_height = None
            if capture is not None:
                ok, image = capture.read()
                if not ok:
                    raise ReplayError(
                        f"video ended before frame_id {frame_id}"
                    )
                video_height, video_width = image.shape[:2]

            try:
                telemetry = interpolate_telemetry(
                    timeline,
                    frame["capture_utc_ns"],
                )
                record = build_replay_record(
                    frame,
                    telemetry,
                    video_frame_index,
                    video_width=video_width,
                    video_height=video_height,
                )
            except (KeyError, SynchronizationError, ReplayError) as exc:
                raise ReplayError(f"cannot replay frame_id {frame_id}: {exc}") from exc

            if realtime:
                capture_offset_s = (
                    frame["capture_utc_ns"] - first_capture_ns
                ) / 1_000_000_000 / speed
                wait_s = replay_started + capture_offset_s - monotonic_fn()
                if wait_s > 0:
                    sleep_fn(wait_s)

            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            frames_processed += 1
            complete_states += 1

        if capture is not None:
            extra_ok, _extra_image = capture.read()
            if extra_ok:
                raise ReplayError(
                    "video contains more frames than frames.jsonl; "
                    "refusing to shift frame identity"
                )
    finally:
        handle.flush()
        handle.close()
        if capture is not None:
            capture.release()

    elapsed_capture_s = (
        frame_index[frame_ids[-1]]["capture_utc_ns"] - first_capture_ns
    ) / 1_000_000_000
    return {
        "ok": True,
        "mission_id": mission_id,
        "frames_processed": frames_processed,
        "complete_states": complete_states,
        "telemetry_source_valid_samples": len(timeline),
        "video_checked": video_checked,
        "video_frames_verified": frames_processed if video_checked else None,
        "capture_duration_seconds": elapsed_capture_s,
        "speed": speed,
        "realtime": realtime,
        "output_path": str(output),
    }


def _load_validated_frame_index(
    frames_path: str | Path,
    *,
    expected_mission_id: str | None = None,
) -> dict[int, dict[str, Any]]:
    try:
        validate_frame_metadata(
            frames_path,
            expected_mission_id=expected_mission_id,
        )
    except FrameMetadataValidationError as exc:
        raise ReplayError(str(exc)) from exc
    return load_frame_index(
        frames_path,
        expected_mission_id=expected_mission_id,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames_jsonl", type=Path)
    parser.add_argument("telemetry_jsonl", type=Path)
    parser.add_argument("output_jsonl", type=Path)
    parser.add_argument(
        "--video",
        type=Path,
        help="optional recorded video; when supplied, frame count is verified",
    )
    parser.add_argument("--mission-id")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument(
        "--no-sleep",
        action="store_true",
        help="validate and emit records immediately instead of real-time pacing",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = replay_mission(
            args.frames_jsonl,
            args.telemetry_jsonl,
            args.output_jsonl,
            video_path=args.video,
            expected_mission_id=args.mission_id,
            speed=args.speed,
            realtime=not args.no_sleep,
            overwrite=args.overwrite,
        )
    except (ReplayError, SynchronizationError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
