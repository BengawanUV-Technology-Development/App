"""Correlate offline detections with capture frames and Ground telemetry."""

from __future__ import annotations

import argparse
import json
import math
import threading
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Iterable


class SynchronizationError(ValueError):
    """Raised when detection/frame/telemetry identity cannot be joined safely."""


_NUMERIC_FIELDS = (
    "latitude",
    "longitude",
    "relative_altitude",
    "absolute_altitude",
    "roll_deg",
    "pitch_deg",
    "yaw_deg",
    "ground_speed_m_s",
    "heading_deg",
    "battery_percent",
)
_REQUIRED_STATE_FIELDS = (
    "latitude",
    "longitude",
    "altitude",
    "roll_deg",
    "pitch_deg",
    "yaw_deg",
)

# Public alias for live consumers.  The offline and live paths must agree on
# what constitutes a complete interpolated UAV state.
REQUIRED_TELEMETRY_FIELDS = _REQUIRED_STATE_FIELDS


class LiveTelemetryTimeline:
    """Thread-safe source-time timeline for detections arriving during flight.

    This is the in-memory counterpart of :func:`load_telemetry_timeline`.  It
    deliberately stores only ``source_time_valid=true`` samples and rebuilds
    the same carry-forward snapshots before delegating interpolation to
    :func:`interpolate_telemetry`.  Ground receive time is never used here.
    """

    def __init__(self, max_samples: int = 8_192) -> None:
        if not isinstance(max_samples, int) or isinstance(max_samples, bool) or max_samples < 2:
            raise ValueError("max_samples must be an integer >= 2")
        self.max_samples = max_samples
        self._lock = threading.RLock()
        self._sequence = 0
        self._samples: list[tuple[int, int, dict[str, Any]]] = []

    def append(self, sample: Mapping[str, Any] | Any) -> bool:
        """Append one valid source-time telemetry sample.

        ``TelemetrySample`` instances are accepted directly, as are their
        JSON-compatible dictionaries.  Invalid or receive-time-only samples
        return ``False`` and do not affect the timeline.
        """

        if hasattr(sample, "to_dict"):
            sample = sample.to_dict()
        if not isinstance(sample, Mapping):
            return False
        if sample.get("source_time_valid") is not True:
            return False
        timestamp = sample.get("source_timestamp")
        payload = sample.get("payload")
        if (
            not isinstance(timestamp, int)
            or isinstance(timestamp, bool)
            or timestamp <= 0
            or not isinstance(payload, Mapping)
        ):
            return False

        with self._lock:
            self._sequence += 1
            self._samples.append(
                (timestamp, self._sequence, {**dict(sample), "payload": dict(payload)})
            )
            if len(self._samples) > self.max_samples:
                self._samples.sort(key=lambda item: (item[0], item[1]))
                del self._samples[: len(self._samples) - self.max_samples]
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        """Return carry-forward snapshots in source timestamp order."""

        with self._lock:
            samples = sorted(self._samples, key=lambda item: (item[0], item[1]))

        state: dict[str, Any] = {}
        timeline: list[dict[str, Any]] = []
        for timestamp, _sequence, record in samples:
            payload = record["payload"]
            state.update(_payload_state_updates(payload))
            snapshot = dict(state)
            snapshot["source_timestamp"] = timestamp
            snapshot["source_clock_domain"] = record.get("source_clock_domain")
            timeline.append(snapshot)
        return timeline

    def interpolate(self, capture_utc_ns: int) -> dict[str, Any]:
        """Interpolate a capture timestamp with the canonical offline helper."""

        return interpolate_telemetry(self.snapshot(), capture_utc_ns)

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
            self._sequence = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._samples)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise SynchronizationError(f"JSONL file does not exist: {source}")
    records: list[dict[str, Any]] = []
    with source.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SynchronizationError(
                    f"invalid JSON at {source}:{line_number}: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise SynchronizationError(
                    f"record at {source}:{line_number} is not an object"
                )
            records.append(record)
    return records


def load_frame_index(
    path: str | Path, expected_mission_id: str | None = None
) -> dict[int, dict[str, Any]]:
    frames = read_jsonl(path)
    index: dict[int, dict[str, Any]] = {}
    mission_ids: set[str] = set()
    for frame in frames:
        if frame.get("record_type", "frame") != "frame":
            continue
        mission_id = frame.get("mission_id")
        frame_id = frame.get("frame_id")
        capture_utc_ns = frame.get("capture_utc_ns")
        if not isinstance(mission_id, str) or not isinstance(frame_id, int):
            raise SynchronizationError("frame identity is incomplete")
        if not isinstance(capture_utc_ns, int) or capture_utc_ns <= 0:
            raise SynchronizationError(
                f"frame {frame_id} has invalid capture_utc_ns"
            )
        if expected_mission_id and mission_id != expected_mission_id:
            raise SynchronizationError("frame mission_id does not match expected mission")
        if frame_id in index:
            raise SynchronizationError(f"duplicate frame_id: {frame_id}")
        mission_ids.add(mission_id)
        index[frame_id] = frame
    if not index:
        raise SynchronizationError("frames.jsonl contains no frame records")
    if len(mission_ids) != 1:
        raise SynchronizationError("frames.jsonl contains multiple mission IDs")
    return index


def load_telemetry_timeline(
    path: str | Path, expected_mission_id: str
) -> list[dict[str, Any]]:
    """Build a source-time-only, carry-forward telemetry timeline.

    Samples with ``source_time_valid=false`` are deliberately discarded.  The
    Ground receive timestamp is never used as a fallback timeline.
    """

    samples = []
    for sequence, record in enumerate(read_jsonl(path)):
        if record.get("record_type") != "telemetry_sample":
            continue
        if record.get("mission_id") != expected_mission_id:
            raise SynchronizationError("telemetry mission_id does not match expected mission")
        if record.get("source_time_valid") is not True:
            continue
        source_timestamp = record.get("source_timestamp")
        if not isinstance(source_timestamp, int) or source_timestamp <= 0:
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        samples.append((source_timestamp, sequence, payload, record))

    if not samples:
        raise SynchronizationError(
            "telemetry contains no source_time_valid=true samples"
        )

    samples.sort(key=lambda item: (item[0], item[1]))
    state: dict[str, Any] = {}
    timeline: list[dict[str, Any]] = []
    for source_timestamp, _sequence, payload, record in samples:
        state.update(_payload_state_updates(payload))
        snapshot = dict(state)
        snapshot["source_timestamp"] = source_timestamp
        snapshot["source_clock_domain"] = record.get("source_clock_domain")
        timeline.append(snapshot)
    return timeline


def interpolate_telemetry(
    timeline: list[dict[str, Any]], capture_utc_ns: int
) -> dict[str, Any]:
    """Interpolate a state using source timestamps bracketing the frame."""

    if not timeline:
        raise SynchronizationError("telemetry timeline is empty")
    before = None
    after = None
    for sample in timeline:
        timestamp = sample["source_timestamp"]
        if timestamp <= capture_utc_ns:
            before = sample
        if timestamp >= capture_utc_ns:
            after = sample
            break
    if before is None or after is None:
        raise SynchronizationError(
            "capture time is outside source telemetry interpolation range"
        )

    before_timestamp = before["source_timestamp"]
    after_timestamp = after["source_timestamp"]
    if before_timestamp == after_timestamp:
        alpha = 0.0
        interpolation = "exact"
    else:
        alpha = (capture_utc_ns - before_timestamp) / (
            after_timestamp - before_timestamp
        )
        interpolation = "linear"

    state: dict[str, Any] = {}
    for field in set(before) | set(after):
        if field in {"source_timestamp", "source_clock_domain"}:
            continue
        left = before.get(field)
        right = after.get(field)
        if _is_number(left) and _is_number(right):
            state[field] = float(left) + (float(right) - float(left)) * alpha
        elif left is not None:
            state[field] = left
        else:
            state[field] = right

    state["altitude"] = state.get("relative_altitude")
    if state["altitude"] is None:
        state["altitude"] = state.get("absolute_altitude")
    state["source_timestamp_before"] = before_timestamp
    state["source_timestamp_after"] = after_timestamp
    state["interpolation"] = interpolation
    state["interpolation_alpha"] = alpha
    state["source_clock_domain"] = (
        before.get("source_clock_domain") or after.get("source_clock_domain")
    )
    return state


def synchronize_detections(
    detections_path: str | Path,
    frames_path: str | Path,
    telemetry_path: str | Path,
    output_path: str | Path,
    *,
    expected_mission_id: str | None = None,
    require_complete_state: bool = True,
) -> dict[str, Any]:
    detections = read_jsonl(detections_path)
    if not detections:
        raise SynchronizationError("detections.jsonl contains no detections")

    mission_ids = {record.get("mission_id") for record in detections}
    if len(mission_ids) != 1 or not all(isinstance(value, str) for value in mission_ids):
        raise SynchronizationError("detections contain multiple or missing mission IDs")
    mission_id = next(iter(mission_ids))
    if expected_mission_id and mission_id != expected_mission_id:
        raise SynchronizationError("detection mission_id does not match expected mission")

    frames = load_frame_index(frames_path, expected_mission_id=mission_id)
    timeline = load_telemetry_timeline(telemetry_path, mission_id)
    output_records: list[dict[str, Any]] = []
    unsynchronized = 0

    for detection in detections:
        frame_id = detection.get("frame_id")
        if not isinstance(frame_id, int) or frame_id not in frames:
            raise SynchronizationError(
                f"detection references unknown frame_id: {frame_id!r}"
            )
        frame = frames[frame_id]
        capture_utc_ns = frame["capture_utc_ns"]
        try:
            telemetry = interpolate_telemetry(timeline, capture_utc_ns)
            if require_complete_state and any(
                telemetry.get(field) is None for field in _REQUIRED_STATE_FIELDS
            ):
                raise SynchronizationError(
                    f"telemetry state is incomplete at frame {frame_id}"
                )
            sync_status = "synchronized"
        except SynchronizationError:
            if require_complete_state:
                raise
            telemetry = {
                field: None
                for field in _REQUIRED_STATE_FIELDS
            }
            telemetry["interpolation"] = "unavailable"
            telemetry["source_timestamp_before"] = None
            telemetry["source_timestamp_after"] = None
            telemetry["interpolation_alpha"] = None
            sync_status = "unsynchronized"
            unsynchronized += 1

        output = dict(detection)
        output["mission_id"] = mission_id
        output["frame_id"] = frame_id
        output["capture_utc_ns"] = capture_utc_ns
        output["capture_time"] = capture_utc_ns
        output["source_pts_ns"] = frame.get("source_pts_ns")
        output["telemetry_sync_status"] = sync_status
        output["telemetry"] = telemetry
        for field in _REQUIRED_STATE_FIELDS:
            output[field] = telemetry.get(field)
        output["latitude"] = telemetry.get("latitude")
        output["longitude"] = telemetry.get("longitude")
        output["altitude"] = telemetry.get("altitude")
        output["roll"] = telemetry.get("roll_deg")
        output["pitch"] = telemetry.get("pitch_deg")
        output["yaw"] = telemetry.get("yaw_deg")
        output_records.append(output)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for record in output_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "mission_id": mission_id,
        "detections": len(output_records),
        "synchronized": len(output_records) - unsynchronized,
        "unsynchronized": unsynchronized,
        "output_path": str(destination),
    }


def _payload_state_updates(payload: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for field in _NUMERIC_FIELDS:
        if field in payload and _is_number(payload[field]):
            updates[field] = payload[field]
    aliases = {
        "ground_speed_m_s": "ground_speed_m_s",
        "heading_deg": "heading_deg",
        "gps_fix": "gps_fix",
        "satellites_visible": "satellites_visible",
        "quaternion": "quaternion",
        "armed": "armed",
        "flight_mode": "flight_mode",
    }
    for target, source in aliases.items():
        if source in payload and payload[source] is not None:
            updates[target] = payload[source]
    if "heading_cdeg" in payload and "heading_deg" not in updates:
        value = payload["heading_cdeg"]
        if _is_number(value) and value >= 0:
            updates["heading_deg"] = float(value) / 100.0
    return updates


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("detections_jsonl", type=Path)
    parser.add_argument("frames_jsonl", type=Path)
    parser.add_argument("telemetry_jsonl", type=Path)
    parser.add_argument("output_jsonl", type=Path)
    parser.add_argument("--mission-id")
    parser.add_argument(
        "--allow-incomplete-state",
        action="store_true",
        help="write null telemetry for detections outside/without a complete bracket",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = synchronize_detections(
            args.detections_jsonl,
            args.frames_jsonl,
            args.telemetry_jsonl,
            args.output_jsonl,
            expected_mission_id=args.mission_id,
            require_complete_state=not args.allow_incomplete_state,
        )
    except SynchronizationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
