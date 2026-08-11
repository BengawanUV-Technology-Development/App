"""Canonical UAV pipeline v2.0 contracts.

This module is intentionally dependency-free so the Jetson and ground services
can validate the same wire contract without importing Flask or Ultralytics.
Schema v1 payloads are rejected: v0.3 is a breaking cutover.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping


SCHEMA_VERSION = "2.0"
CAMERA_ID = "arducam"
COORDINATE_STATUS = "not_available"
MISSION_STATUSES = frozenset({"CREATED", "RECORDING", "COMPLETED", "FAILED", "IMPORTED"})
COMPONENT_STATUSES = frozenset(
    {"STARTING", "RUNNING", "DEGRADED", "STALE", "STOPPING", "STOPPED", "FAILED", "DISABLED"}
)
COMMAND_STATUSES = frozenset(
    {"PENDING", "SENT", "ACKNOWLEDGED", "REJECTED", "TIMEOUT", "FAILED"}
)


class ContractError(ValueError):
    """Raised when a v2.0 payload violates the frozen contract."""


def _required_int(payload: Mapping[str, Any], key: str, minimum: int = 0) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{key} must be an integer >= {minimum}")
    return value


def validate_mission_id(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("mission-"):
        raise ContractError("mission_id must be mission-<uuid>")
    try:
        uuid.UUID(value.removeprefix("mission-"))
    except (ValueError, AttributeError) as exc:
        raise ContractError("mission_id must be mission-<uuid>") from exc
    return value


@dataclass(frozen=True, slots=True)
class FrameIdentity:
    mission_id: str
    capture_epoch: int
    frame_id: int
    camera_id: str
    capture_utc_ns: int
    capture_monotonic_ns: int
    source_pts_ns: int

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FrameIdentity":
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ContractError("schema_version must be 2.0")
        mission_id = validate_mission_id(payload.get("mission_id"))
        camera_id = payload.get("camera_id")
        if camera_id != CAMERA_ID:
            raise ContractError("camera_id must be arducam for the v0.3 release")
        return cls(
            mission_id=mission_id,
            capture_epoch=_required_int(payload, "capture_epoch", 1),
            frame_id=_required_int(payload, "frame_id"),
            camera_id=camera_id,
            capture_utc_ns=_required_int(payload, "capture_utc_ns", 1),
            capture_monotonic_ns=_required_int(payload, "capture_monotonic_ns"),
            source_pts_ns=_required_int(payload, "source_pts_ns"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @property
    def key(self) -> tuple[str, int, int, str]:
        return self.mission_id, self.capture_epoch, self.frame_id, self.camera_id


def validate_normalized_xyxy(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ContractError("bbox_normalized_xyxy must contain four numbers")
    try:
        x1, y1, x2, y2 = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ContractError("bbox_normalized_xyxy must contain four numbers") from exc
    if not all(math.isfinite(item) for item in (x1, y1, x2, y2)):
        raise ContractError("bbox_normalized_xyxy values must be finite")
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise ContractError("bbox_normalized_xyxy must satisfy 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1")
    return x1, y1, x2, y2


def validate_detection_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    identity = FrameIdentity.from_mapping(payload)
    try:
        detection_id = str(uuid.UUID(str(payload.get("detection_id"))))
    except (ValueError, AttributeError) as exc:
        raise ContractError("detection_id must be a UUID") from exc
    label = payload.get("class")
    if not isinstance(label, str) or not label.strip():
        raise ContractError("class must be a non-empty string")
    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ContractError("confidence must be between 0 and 1")
    coordinate = payload.get("coordinate")
    if coordinate != {"status": COORDINATE_STATUS}:
        raise ContractError("coordinate must be exactly {'status': 'not_available'}")
    return {
        **identity.as_dict(),
        "detection_id": detection_id,
        "class": label.strip(),
        "confidence": float(confidence),
        "bbox_normalized_xyxy": list(validate_normalized_xyxy(payload.get("bbox_normalized_xyxy"))),
        "coordinate": {"status": COORDINATE_STATUS},
    }
