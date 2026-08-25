"""Capture-time frame metadata contract for the Jetson recording agent.

This module deliberately has no GStreamer dependency.  The recording agent
uses :class:`FrameMetadataWriter` from the camera-source/tee callback and
passes the source ``Gst.Buffer`` to :meth:`record_gst_buffer`.  The callback
must run at capture time, before encoding or any offline processing, so the
writer never derives ``source_pts_ns`` from a later frame arrival time.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


FRAME_METADATA_SCHEMA_VERSION = 1
FRAME_RECORD_TYPE = "frame"
REQUIRED_FRAME_FIELDS = (
    "mission_id",
    "capture_epoch",
    "frame_id",
    "camera_id",
    "capture_utc_ns",
    "capture_monotonic_ns",
    "source_pts_ns",
)
_MISSION_ID_RE = re.compile(
    r"^mission-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_GST_CLOCK_TIME_NONE = (1 << 64) - 1


class FrameMetadataError(ValueError):
    """Raised when a capture frame cannot satisfy the metadata contract."""


class FrameMetadataValidationError(FrameMetadataError):
    """Raised when an existing ``frames.jsonl`` is not internally consistent."""

    def __init__(self, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


@dataclass(frozen=True)
class CaptureClock:
    """Two clocks sampled together at the capture callback."""

    utc_ns: int
    monotonic_ns: int

    @classmethod
    def now(cls) -> "CaptureClock":
        return cls(utc_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())


@dataclass(frozen=True)
class FrameMetadata:
    """One immutable canonical frame identity record."""

    mission_id: str
    capture_epoch: int
    frame_id: int
    camera_id: str
    capture_utc_ns: int
    capture_monotonic_ns: int
    source_pts_ns: int | None

    def to_dict(self) -> dict[str, Any]:
        # Keep the canonical fields explicit and in contract order.  The
        # schema/record markers are additive and make mixed JSONL inspection
        # safer without changing the identity fields.
        return {
            "schema_version": FRAME_METADATA_SCHEMA_VERSION,
            "record_type": FRAME_RECORD_TYPE,
            "mission_id": self.mission_id,
            "capture_epoch": self.capture_epoch,
            "frame_id": self.frame_id,
            "camera_id": self.camera_id,
            "capture_utc_ns": self.capture_utc_ns,
            "capture_monotonic_ns": self.capture_monotonic_ns,
            "source_pts_ns": self.source_pts_ns,
        }


class FrameMetadataWriter:
    """Persist capture-time frame identities to ``frames.jsonl``.

    The writer is intentionally synchronous: a successful return means the
    JSON line has reached the OS file buffer.  The recording agent should use
    a bounded capture-side queue if its GStreamer callback must not perform
    disk I/O directly.  Queue drops must be surfaced to the caller rather
    than silently inventing or re-timestamping a frame.
    """

    def __init__(
        self,
        path: str | Path,
        mission_id: str,
        camera_id: str,
        capture_epoch: int = 1,
        *,
        append: bool = False,
        require_source_pts: bool = True,
    ) -> None:
        _validate_mission_id(mission_id)
        _validate_positive_int("capture_epoch", capture_epoch)
        if not camera_id or not isinstance(camera_id, str):
            raise FrameMetadataError("camera_id must be a non-empty string")

        self.path = Path(path)
        self.mission_id = mission_id
        self.camera_id = camera_id
        self.capture_epoch = capture_epoch
        self.append = append
        self.require_source_pts = require_source_pts

        self._handle = None
        self._last_frame_id: int | None = None
        self._last_capture_utc_ns: int | None = None
        self._last_capture_monotonic_ns: int | None = None
        self._last_source_pts_ns: int | None = None
        self._last_capture_epoch: int | None = None
        self._frames_written = 0
        self._missing_source_pts = 0

    @property
    def active(self) -> bool:
        return self._handle is not None

    def start(self) -> dict[str, Any]:
        if self.active:
            raise FrameMetadataError("frame metadata writer is already active")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not self.append:
            raise FrameMetadataError(
                f"refusing to overwrite existing frame metadata: {self.path}"
            )

        mode = "a" if self.path.exists() else "x"
        if mode == "a":
            self._restore_existing_state()
        self._handle = self.path.open(mode, encoding="utf-8", buffering=1)
        return self.status()

    def record_frame(
        self,
        *,
        capture_utc_ns: int,
        capture_monotonic_ns: int,
        source_pts_ns: int | None,
        frame_id: int | None = None,
    ) -> dict[str, Any]:
        if not self.active:
            raise FrameMetadataError("frame metadata writer is not active")

        _validate_positive_int("capture_utc_ns", capture_utc_ns)
        _validate_positive_int("capture_monotonic_ns", capture_monotonic_ns)
        if source_pts_ns is None:
            self._missing_source_pts += 1
            if self.require_source_pts:
                raise FrameMetadataError(
                    "capture source did not provide source_pts_ns; "
                    "refusing to synthesize a post-processing timestamp"
                )
        else:
            _validate_nonnegative_int("source_pts_ns", source_pts_ns)

        if frame_id is None:
            frame_id = 0 if self._last_frame_id is None else self._last_frame_id + 1
        _validate_nonnegative_int("frame_id", frame_id)

        if self._last_frame_id is not None and frame_id <= self._last_frame_id:
            raise FrameMetadataError(
                f"frame_id must increase: {frame_id} <= {self._last_frame_id}"
            )
        if (
            self._last_capture_utc_ns is not None
            and capture_utc_ns < self._last_capture_utc_ns
        ):
            raise FrameMetadataError("capture_utc_ns moved backwards")
        if (
            self._last_capture_monotonic_ns is not None
            and capture_monotonic_ns < self._last_capture_monotonic_ns
        ):
            raise FrameMetadataError("capture_monotonic_ns moved backwards")
        same_capture_epoch = (
            self._last_capture_epoch is None
            or self.capture_epoch == self._last_capture_epoch
        )
        if (
            source_pts_ns is not None
            and self._last_source_pts_ns is not None
            and same_capture_epoch
            and source_pts_ns < self._last_source_pts_ns
        ):
            raise FrameMetadataError("source_pts_ns moved backwards")

        metadata = FrameMetadata(
            mission_id=self.mission_id,
            capture_epoch=self.capture_epoch,
            frame_id=frame_id,
            camera_id=self.camera_id,
            capture_utc_ns=capture_utc_ns,
            capture_monotonic_ns=capture_monotonic_ns,
            source_pts_ns=source_pts_ns,
        )
        self._handle.write(json.dumps(metadata.to_dict(), separators=(",", ":")) + "\n")
        self._handle.flush()

        self._last_frame_id = frame_id
        self._last_capture_utc_ns = capture_utc_ns
        self._last_capture_monotonic_ns = capture_monotonic_ns
        if source_pts_ns is not None:
            self._last_source_pts_ns = source_pts_ns
        self._last_capture_epoch = self.capture_epoch
        self._frames_written += 1
        return metadata.to_dict()

    def record_gst_buffer(
        self,
        buffer: Any,
        *,
        frame_id: int | None = None,
        capture_clock: CaptureClock | None = None,
    ) -> dict[str, Any]:
        """Record a source buffer without deriving PTS from wall-clock time.

        Attach this to the camera-source pad or equivalent capture callback.
        ``buffer.pts`` is copied verbatim as nanoseconds; ``None`` and
        ``GST_CLOCK_TIME_NONE`` are treated as missing and rejected by default.
        """

        source_pts_ns = gst_buffer_pts_ns(buffer)
        clock = capture_clock or CaptureClock.now()
        return self.record_frame(
            frame_id=frame_id,
            capture_utc_ns=clock.utc_ns,
            capture_monotonic_ns=clock.monotonic_ns,
            source_pts_ns=source_pts_ns,
        )

    def stop(self) -> dict[str, Any]:
        if self._handle is None:
            return self.status()
        self._handle.flush()
        try:
            os.fsync(self._handle.fileno())
        finally:
            self._handle.close()
            self._handle = None
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "mission_id": self.mission_id,
            "camera_id": self.camera_id,
            "capture_epoch": self.capture_epoch,
            "active": self.active,
            "frames_written": self._frames_written,
            "missing_source_pts": self._missing_source_pts,
        }

    def _restore_existing_state(self) -> None:
        report = validate_frame_metadata(
            self.path,
            expected_mission_id=self.mission_id,
            require_source_pts=False,
        )
        self._frames_written = report["frame_count"]
        self._last_frame_id = report["last_frame_id"]
        self._last_capture_utc_ns = report["last_capture_utc_ns"]
        self._last_capture_monotonic_ns = report["last_capture_monotonic_ns"]
        self._last_source_pts_ns = report["last_source_pts_ns"]
        self._last_capture_epoch = report["last_capture_epoch"]
        if self.capture_epoch < (self._last_capture_epoch or self.capture_epoch):
            raise FrameMetadataError(
                "capture_epoch cannot move backwards when appending frame metadata"
            )


def capture_clock_now() -> CaptureClock:
    """Return UTC and monotonic capture clocks sampled at the same point."""

    return CaptureClock.now()


def gst_buffer_pts_ns(buffer: Any) -> int | None:
    """Extract a GStreamer buffer PTS without importing GStreamer."""

    value = getattr(buffer, "pts", None)
    if value is None or value == _GST_CLOCK_TIME_NONE:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise FrameMetadataError(f"invalid Gst.Buffer.pts: {value!r}") from exc
    if value < 0:
        return None
    return value


def validate_frame_metadata(
    path: str | Path,
    *,
    expected_mission_id: str | None = None,
    require_source_pts: bool = True,
) -> dict[str, Any]:
    """Validate frame identity, timestamp ordering, and mission consistency."""

    metadata_path = Path(path)
    if not metadata_path.is_file():
        raise FrameMetadataValidationError(
            f"frame metadata file does not exist: {metadata_path}"
        )

    frame_count = 0
    mission_ids: set[str] = set()
    camera_ids: set[str] = set()
    capture_epochs: set[int] = set()
    previous_frame_id: int | None = None
    previous_utc: int | None = None
    previous_monotonic: int | None = None
    previous_pts: int | None = None
    previous_capture_epoch: int | None = None
    last_capture_epoch: int | None = None
    missing_source_pts = 0

    try:
        handle = metadata_path.open(encoding="utf-8")
    except OSError as exc:
        raise FrameMetadataValidationError(str(exc)) from exc

    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise FrameMetadataValidationError(
                    f"invalid JSON at line {line_number}: {exc}"
                ) from exc
            if not isinstance(entry, dict):
                raise FrameMetadataValidationError(
                    f"frame record at line {line_number} is not an object"
                )
            missing = [field for field in REQUIRED_FRAME_FIELDS if field not in entry]
            if missing:
                raise FrameMetadataValidationError(
                    f"missing fields at line {line_number}: {', '.join(missing)}"
                )
            if entry.get("record_type", FRAME_RECORD_TYPE) != FRAME_RECORD_TYPE:
                raise FrameMetadataValidationError(
                    f"unexpected record_type at line {line_number}"
                )

            mission_id = entry["mission_id"]
            if not isinstance(mission_id, str) or not _MISSION_ID_RE.fullmatch(mission_id):
                raise FrameMetadataValidationError(
                    f"invalid mission_id at line {line_number}: {mission_id!r}"
                )
            if expected_mission_id and mission_id != expected_mission_id:
                raise FrameMetadataValidationError(
                    f"mission_id mismatch at line {line_number}: "
                    f"{mission_id!r} != {expected_mission_id!r}"
                )
            mission_ids.add(mission_id)

            frame_id = _read_nonnegative_int(entry, "frame_id", line_number)
            capture_epoch = _read_positive_int(entry, "capture_epoch", line_number)
            capture_utc_ns = _read_positive_int(entry, "capture_utc_ns", line_number)
            capture_monotonic_ns = _read_positive_int(
                entry, "capture_monotonic_ns", line_number
            )
            camera_id = entry["camera_id"]
            if not isinstance(camera_id, str) or not camera_id:
                raise FrameMetadataValidationError(
                    f"invalid camera_id at line {line_number}"
                )
            camera_ids.add(camera_id)

            source_pts_ns = entry["source_pts_ns"]
            if source_pts_ns is None:
                missing_source_pts += 1
                if require_source_pts:
                    raise FrameMetadataValidationError(
                        f"missing source_pts_ns at line {line_number}"
                    )
            else:
                source_pts_ns = _read_nonnegative_int(
                    entry, "source_pts_ns", line_number
                )

            if previous_frame_id is not None and frame_id <= previous_frame_id:
                raise FrameMetadataValidationError(
                    f"frame_id is not increasing at line {line_number}"
                )
            if (
                previous_capture_epoch is not None
                and capture_epoch < previous_capture_epoch
            ):
                raise FrameMetadataValidationError(
                    f"capture_epoch moved backwards at line {line_number}"
                )
            if previous_utc is not None and capture_utc_ns < previous_utc:
                raise FrameMetadataValidationError(
                    f"capture_utc_ns moved backwards at line {line_number}"
                )
            if (
                previous_monotonic is not None
                and capture_monotonic_ns < previous_monotonic
            ):
                raise FrameMetadataValidationError(
                    f"capture_monotonic_ns moved backwards at line {line_number}"
                )
            if (
                previous_capture_epoch == capture_epoch
                and previous_pts is not None
                and source_pts_ns is not None
                and source_pts_ns < previous_pts
            ):
                raise FrameMetadataValidationError(
                    f"source_pts_ns moved backwards at line {line_number}"
                )

            previous_frame_id = frame_id
            previous_utc = capture_utc_ns
            previous_monotonic = capture_monotonic_ns
            previous_capture_epoch = capture_epoch
            previous_pts = source_pts_ns
            last_capture_epoch = capture_epoch
            capture_epochs.add(capture_epoch)
            frame_count += 1

    if frame_count == 0:
        raise FrameMetadataValidationError("frames.jsonl contains no frame records")
    if len(mission_ids) != 1:
        raise FrameMetadataValidationError("frames.jsonl contains multiple mission IDs")

    return {
        "path": str(metadata_path),
        "frame_count": frame_count,
        "mission_id": next(iter(mission_ids)),
        "camera_ids": sorted(camera_ids),
        "capture_epochs": sorted(capture_epochs),
        "first_frame_id": _first_frame_id(metadata_path),
        "last_frame_id": previous_frame_id,
        "last_capture_utc_ns": previous_utc,
        "last_capture_monotonic_ns": previous_monotonic,
        "last_source_pts_ns": previous_pts,
        "last_capture_epoch": last_capture_epoch,
        "missing_source_pts": missing_source_pts,
    }


def _validate_mission_id(value: str) -> None:
    if not isinstance(value, str) or not _MISSION_ID_RE.fullmatch(value):
        raise FrameMetadataError(f"invalid mission_id: {value!r}")


def _validate_positive_int(name: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise FrameMetadataError(f"{name} must be a positive integer")


def _validate_nonnegative_int(name: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise FrameMetadataError(f"{name} must be a non-negative integer")


def _read_positive_int(entry: dict[str, Any], name: str, line_number: int) -> int:
    value = entry[name]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise FrameMetadataValidationError(
            f"{name} must be a positive integer at line {line_number}"
        )
    return value


def _read_nonnegative_int(entry: dict[str, Any], name: str, line_number: int) -> int:
    value = entry[name]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise FrameMetadataValidationError(
            f"{name} must be a non-negative integer at line {line_number}"
        )
    return value


def _first_frame_id(path: Path) -> int | None:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                return json.loads(line)["frame_id"]
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames_jsonl", type=Path)
    parser.add_argument("--mission-id")
    parser.add_argument(
        "--allow-missing-source-pts",
        action="store_true",
        help="validate structure/order while allowing null source_pts_ns",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = validate_frame_metadata(
            args.frames_jsonl,
            expected_mission_id=args.mission_id,
            require_source_pts=not args.allow_missing_source_pts,
        )
    except FrameMetadataValidationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"ok": True, **report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
