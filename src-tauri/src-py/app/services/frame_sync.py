"""Exact canonical identity matching for registered RTP streams and metadata."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from .rtp_identity import RtpTimestampUnwrapper, parse_rtp_packet


class FrameSyncError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CanonicalKey:
    mission_id: str
    capture_epoch: int
    frame_id: int
    camera_id: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CanonicalKey":
        try:
            mission_id = payload["mission_id"]
            uuid.UUID(str(mission_id).removeprefix("mission-"))
            capture_epoch = int(payload["capture_epoch"])
            frame_id = int(payload["frame_id"])
            camera_id = payload["camera_id"]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise FrameSyncError("invalid canonical frame identity") from exc
        if not str(mission_id).startswith("mission-") or capture_epoch < 1 or frame_id < 0 or camera_id != "arducam":
            raise FrameSyncError("invalid canonical frame identity")
        return cls(str(mission_id), capture_epoch, frame_id, camera_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "capture_epoch": self.capture_epoch,
            "frame_id": self.frame_id,
            "camera_id": self.camera_id,
        }


class StreamRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._streams: dict[int, dict[str, Any]] = {}
        self._generation = 0

    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("schema_version") != "2.0":
            raise FrameSyncError("stream registration must use schema_version 2.0")
        probe = {**payload, "frame_id": 0}
        key = CanonicalKey.from_payload(probe)
        try:
            ssrc = int(payload["ssrc"])
            width = int(payload["width"])
            height = int(payload["height"])
            fps = float(payload["fps"])
            clock_rate = int(payload["rtp_clock_rate"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FrameSyncError("invalid stream registration fields") from exc
        if not 0 <= ssrc <= 0xFFFFFFFF or min(width, height) < 16 or fps <= 0 or clock_rate != 90_000:
            raise FrameSyncError("invalid stream registration values")
        with self._lock:
            self._generation += 1
            registration = {
                "schema_version": "2.0",
                **key.as_dict(),
                "ssrc": ssrc,
                "width": width,
                "height": height,
                "fps": fps,
                "rtp_clock_rate": clock_rate,
                "generation": self._generation,
                "registered_monotonic_ns": time.monotonic_ns(),
            }
            registration.pop("frame_id")
            self._streams = {ssrc: registration}
            return dict(registration)

    def resolve(self, ssrc: int, frame_id: int) -> tuple[CanonicalKey, dict[str, Any]]:
        with self._lock:
            registration = self._streams.get(ssrc)
        if registration is None:
            raise FrameSyncError(f"unregistered RTP SSRC: {ssrc}")
        key = CanonicalKey(
            registration["mission_id"], registration["capture_epoch"], frame_id, registration["camera_id"]
        )
        return key, dict(registration)

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(next(iter(self._streams.values()))) if self._streams else None


@dataclass(slots=True)
class MatchedFrame:
    key: CanonicalKey
    jpeg: bytes
    metadata: dict[str, Any] | None
    rtp_timestamp: int
    decoded_monotonic_ns: int
    state: str


class FrameSynchronizer:
    """Instant, non-blocking video release.

    A video frame is shown the moment it decodes: opportunistically
    carrying a detection if one for the same identity already arrived, but
    never held waiting for one. An earlier version held every video frame
    for up to a fixed window on the chance its metadata would arrive --
    that forced the *entire* live feed to lag by that window, not just the
    frames that ended up matched, since every frame (matched or not) was
    held for the same wait. Detections that miss this opportunistic window
    are not lost: they are reviewed post-flight from the recording instead
    of live (see docs/post-flight-detection-snapshots.md), so the live feed
    can be real-time with zero added latency.
    """

    def __init__(self, capacity: int = 120):
        self.capacity = capacity
        self._lock = threading.RLock()
        self._metadata: OrderedDict[CanonicalKey, tuple[dict[str, Any], int]] = OrderedDict()
        self.metadata_evicted = 0

    @staticmethod
    def _bounded(mapping: OrderedDict, capacity: int) -> bool:
        evicted = False
        while len(mapping) > capacity:
            mapping.popitem(last=False)
            evicted = True
        return evicted

    def reset(self) -> None:
        with self._lock:
            self._metadata.clear()

    def push_metadata(self, payload: dict[str, Any], now_ns: int | None = None) -> bool:
        key = CanonicalKey.from_payload(payload)
        now_ns = now_ns or time.monotonic_ns()
        with self._lock:
            self._metadata[key] = (payload, now_ns)
            self._metadata.move_to_end(key)
            if self._bounded(self._metadata, self.capacity):
                self.metadata_evicted += 1
            return True

    def match_video(
        self, key: CanonicalKey, jpeg: bytes, rtp_timestamp: int, now_ns: int | None = None
    ) -> MatchedFrame:
        """Release this video frame immediately: MATCHED if metadata for
        this exact identity already arrived, LIVE (no box, not an error --
        just nothing to show yet) otherwise."""

        now_ns = now_ns or time.monotonic_ns()
        with self._lock:
            metadata_item = self._metadata.pop(key, None)
        if metadata_item is not None:
            return MatchedFrame(key, jpeg, metadata_item[0], rtp_timestamp, now_ns, "MATCHED")
        return MatchedFrame(key, jpeg, None, rtp_timestamp, now_ns, "LIVE")


class RtpIdentityTracker:
    """Reject duplicates/conflicts while retaining reorder and wrap correctness."""

    def __init__(self, registry: StreamRegistry, capacity: int = 4096):
        self.registry = registry
        self.capacity = capacity
        self._seen: OrderedDict[tuple[int, int, int], None] = OrderedDict()
        self._timestamp_identity: OrderedDict[tuple[int, int], int] = OrderedDict()
        self._unwrappers: dict[int, RtpTimestampUnwrapper] = {}

    def reset(self) -> None:
        self._seen.clear()
        self._timestamp_identity.clear()
        self._unwrappers.clear()

    def observe(self, packet_bytes: bytes) -> tuple[CanonicalKey, int, int] | None:
        packet = parse_rtp_packet(packet_bytes)
        if packet.frame_id is None:
            raise FrameSyncError("RTP packet is missing the frame_id extension")
        duplicate_key = (packet.ssrc, packet.sequence, packet.timestamp)
        if duplicate_key in self._seen:
            return None
        self._seen[duplicate_key] = None
        self._bounded(self._seen, self.capacity)
        timestamp_key = (packet.ssrc, packet.timestamp)
        previous = self._timestamp_identity.get(timestamp_key)
        if previous is not None and previous != packet.frame_id:
            raise FrameSyncError("conflicting frame_id for one RTP timestamp")
        self._timestamp_identity[timestamp_key] = packet.frame_id
        self._bounded(self._timestamp_identity, self.capacity)
        key, _registration = self.registry.resolve(packet.ssrc, packet.frame_id)
        unwrapper = self._unwrappers.setdefault(packet.ssrc, RtpTimestampUnwrapper())
        return key, packet.timestamp, unwrapper.unwrap(packet.timestamp)

    @staticmethod
    def _bounded(mapping: OrderedDict, capacity: int) -> None:
        while len(mapping) > capacity:
            mapping.popitem(last=False)
