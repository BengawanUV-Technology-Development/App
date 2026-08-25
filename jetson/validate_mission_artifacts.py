"""Validate short-flight artifacts before offline inference."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from jetson.frame_metadata import (
    FrameMetadataValidationError,
    validate_frame_metadata,
)


class MissionArtifactValidationError(ValueError):
    """Raised when a short-flight artifact set is incomplete or invalid."""


def resolve_artifact_directory(
    mission_path: str | Path,
    *,
    capture_epoch: int | None = None,
) -> tuple[Path, int | None]:
    """Resolve either an epoch directory or a Jetson mission directory.

    The deployed Jetson agent stores evidence under
    ``<mission_id>/epochs/<capture_epoch>/`` while local fixtures and older
    agents may expose ``video.mp4`` and ``frames.jsonl`` directly.  Accept
    both layouts so validation follows the actual mission contract without
    copying or renaming evidence.
    """

    directory = Path(mission_path)
    if not directory.is_dir():
        raise MissionArtifactValidationError(
            f"mission artifact directory does not exist: {directory}"
        )
    if (directory / "video.mp4").is_file() or (directory / "frames.jsonl").is_file():
        return directory, _epoch_from_directory_name(directory)

    epochs_root = directory / "epochs"
    if not epochs_root.is_dir():
        raise MissionArtifactValidationError(
            f"mission directory has no direct artifacts or epochs directory: {directory}"
        )

    candidates = []
    for child in epochs_root.iterdir():
        if not child.is_dir():
            continue
        epoch = _epoch_from_directory_name(child)
        if epoch is None or (child / "video.mp4").is_file() is False:
            continue
        if not (child / "frames.jsonl").is_file():
            continue
        candidates.append((epoch, child))
    if not candidates:
        raise MissionArtifactValidationError(
            f"mission has no complete video/frame epoch artifacts: {directory}"
        )

    if capture_epoch is not None:
        for epoch, child in candidates:
            if epoch == capture_epoch:
                return child, epoch
        raise MissionArtifactValidationError(
            f"capture epoch {capture_epoch} has no complete artifacts in {directory}"
        )
    selected_epoch, selected_directory = max(candidates, key=lambda item: item[0])
    return selected_directory, selected_epoch


def _epoch_from_directory_name(directory: Path) -> int | None:
    try:
        value = int(directory.name)
    except ValueError:
        return None
    return value if value > 0 else None


def validate_telemetry_jsonl(path: str | Path, expected_mission_id: str) -> dict[str, Any]:
    telemetry_path = Path(path)
    if not telemetry_path.is_file():
        raise MissionArtifactValidationError(
            f"telemetry file does not exist: {telemetry_path}"
        )

    record_count = 0
    telemetry_sample_count = 0
    source_time_valid_count = 0
    mission_ids: set[str] = set()
    message_types: set[str] = set()
    with telemetry_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MissionArtifactValidationError(
                    f"invalid telemetry JSON at line {line_number}: {exc}"
                ) from exc
            if not isinstance(entry, dict):
                raise MissionArtifactValidationError(
                    f"telemetry record at line {line_number} is not an object"
                )
            if entry.get("mission_id") != expected_mission_id:
                raise MissionArtifactValidationError(
                    f"telemetry mission_id mismatch at line {line_number}"
                )
            if entry.get("receive_timestamp") is None:
                raise MissionArtifactValidationError(
                    f"telemetry receive_timestamp missing at line {line_number}"
                )
            mission_ids.add(entry["mission_id"])
            message_type = entry.get("message_type")
            if isinstance(message_type, str):
                message_types.add(message_type)
            record_count += 1
            if entry.get("record_type") == "telemetry_sample":
                telemetry_sample_count += 1
                if entry.get("source_time_valid") is True:
                    source_time_valid_count += 1

    if not record_count:
        raise MissionArtifactValidationError("telemetry.jsonl contains no records")
    if not telemetry_sample_count:
        raise MissionArtifactValidationError(
            "telemetry.jsonl contains no telemetry_sample records"
        )
    if not source_time_valid_count:
        raise MissionArtifactValidationError(
            "telemetry.jsonl contains no source_time_valid=true samples"
        )

    return {
        "path": str(telemetry_path),
        "record_count": record_count,
        "telemetry_sample_count": telemetry_sample_count,
        "source_time_valid_count": source_time_valid_count,
        "mission_ids": sorted(mission_ids),
        "message_types": sorted(message_types),
    }


def probe_video(video_path: Path) -> dict[str, Any]:
    if not video_path.is_file():
        raise MissionArtifactValidationError(f"video does not exist: {video_path}")
    size_bytes = video_path.stat().st_size
    if size_bytes <= 0:
        raise MissionArtifactValidationError(f"video is empty: {video_path}")

    result: dict[str, Any] = {
        "path": str(video_path),
        "size_bytes": size_bytes,
        "probe": "not_run",
    }
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        result["probe_reason"] = "ffprobe is not installed"
        return result

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_name,width,height",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        details = json.loads(completed.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise MissionArtifactValidationError(
            f"video probe failed for {video_path}: {exc}"
        ) from exc
    result["probe"] = "ok"
    result["details"] = details
    return result


def validate_mission_artifacts(
    mission_dir: str | Path,
    telemetry_path: str | Path,
    *,
    expected_mission_id: str | None = None,
    capture_epoch: int | None = None,
) -> dict[str, Any]:
    directory, resolved_epoch = resolve_artifact_directory(
        mission_dir,
        capture_epoch=capture_epoch,
    )
    frames_path = directory / "frames.jsonl"
    video_path = directory / "video.mp4"

    try:
        frame_report = validate_frame_metadata(
            frames_path,
            expected_mission_id=expected_mission_id,
        )
    except FrameMetadataValidationError as exc:
        raise MissionArtifactValidationError(str(exc)) from exc

    return {
        "ok": True,
        "mission_id": frame_report["mission_id"],
        "artifact_directory": str(directory),
        "capture_epoch": resolved_epoch,
        "video": probe_video(video_path),
        "frames": frame_report,
        "telemetry": validate_telemetry_jsonl(
            telemetry_path,
            frame_report["mission_id"],
        ),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mission_dir", type=Path)
    parser.add_argument("--telemetry", required=True, type=Path)
    parser.add_argument("--mission-id")
    parser.add_argument("--capture-epoch", type=int)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = validate_mission_artifacts(
            args.mission_dir,
            args.telemetry,
            expected_mission_id=args.mission_id,
            capture_epoch=args.capture_epoch,
        )
    except MissionArtifactValidationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
