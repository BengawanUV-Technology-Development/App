"""Receive-only Jetson detections and join them to live Ground telemetry."""

from __future__ import annotations

import copy
import hmac
import json
import math
import threading
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.models import TelemetrySample
from postflight.coordinate_reconstruction import (
    CoordinateReconstructionAdapter,
    NOT_AVAILABLE,
)
from postflight.synchronization import (
    LiveTelemetryTimeline,
    REQUIRED_TELEMETRY_FIELDS,
    SynchronizationError,
)


VISION_DETECTION_SCHEMA_VERSION = 1
_MAX_DETECTION_ID_LENGTH = 256


class VisionIngestError(ValueError):
    """A detection was rejected without affecting recording or telemetry."""

    def __init__(self, message: str, code: str = "INVALID_DETECTION") -> None:
        super().__init__(message)
        self.code = code


class VisionDetectionService:
    """Mission-scoped, bounded live detection joiner.

    Jetson sends small JSON detection events; the high-resolution video and
    frame sidecars remain on Jetson.  This service stores one auditable Ground
    artifact per accepted detection and never uses the inbound coordinate
    placeholder or Ground receive time to create a target position.
    """

    def __init__(
        self,
        *,
        coordinate_adapter: CoordinateReconstructionAdapter | None = None,
        coordinate_enabled: bool = False,
        altitude_reference: str | None = None,
        camera_attitude_frame: str | None = None,
        timeline_size: int = 8_192,
        recent_detection_limit: int = 64,
        pending_detection_limit: int = 256,
    ) -> None:
        if not isinstance(recent_detection_limit, int) or recent_detection_limit < 1:
            raise ValueError("recent_detection_limit must be a positive integer")
        if not isinstance(pending_detection_limit, int) or pending_detection_limit < 1:
            raise ValueError("pending_detection_limit must be a positive integer")
        self.coordinate_adapter = coordinate_adapter or CoordinateReconstructionAdapter(None)
        self.coordinate_enabled = bool(coordinate_enabled)
        self.altitude_reference = altitude_reference.strip() if altitude_reference else None
        self.camera_attitude_frame = (
            camera_attitude_frame.strip() if camera_attitude_frame else None
        )
        self.timeline_size = timeline_size
        self.recent_detection_limit = recent_detection_limit
        self.pending_detection_limit = pending_detection_limit

        self._lock = threading.RLock()
        self._mission_id: str | None = None
        self._artifact_path: Path | None = None
        self._artifact_handle = None
        self._timeline = LiveTelemetryTimeline(max_samples=timeline_size)
        self._detections: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._pending: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._seen_fingerprints: dict[str, tuple[Any, ...]] = {}
        self._latest_overlay: dict[str, Any] | None = None
        self._accepted = 0
        self._rejected = 0
        self._pending_wakeup = threading.Event()
        self._pending_stop = threading.Event()
        self._pending_thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._mission_id is not None

    @property
    def mission_id(self) -> str | None:
        with self._lock:
            return self._mission_id

    @property
    def artifact_path(self) -> Path | None:
        with self._lock:
            return self._artifact_path

    def start(self, mission_id: str, artifact_dir: str | Path | None = None) -> dict[str, Any]:
        with self._lock:
            if self._mission_id is not None:
                raise VisionIngestError(
                    f"vision mission {self._mission_id} is already active",
                    code="MISSION_ALREADY_ACTIVE",
                )
            if not isinstance(mission_id, str) or not mission_id.strip():
                raise VisionIngestError("mission_id is required", code="MISSION_ID_REQUIRED")

            artifact_path = None
            handle = None
            if artifact_dir is not None:
                directory = Path(artifact_dir)
                directory.mkdir(parents=True, exist_ok=True)
                artifact_path = directory / "detections_with_telemetry.jsonl"
                try:
                    handle = artifact_path.open("x", encoding="utf-8", buffering=1)
                except FileExistsError as exc:
                    raise VisionIngestError(
                        f"refusing to overwrite existing detection artifact: {artifact_path}",
                        code="ARTIFACT_EXISTS",
                    ) from exc

            self._mission_id = mission_id.strip()
            self._artifact_path = artifact_path
            self._artifact_handle = handle
            self._timeline = LiveTelemetryTimeline(max_samples=self.timeline_size)
            self._detections.clear()
            self._pending.clear()
            self._seen_fingerprints.clear()
            self._latest_overlay = None
            self._accepted = 0
            self._rejected = 0
            self._pending_stop.clear()
            self._pending_wakeup.clear()
            self._pending_thread = threading.Thread(
                target=self._pending_loop,
                name=f"vision-pending-{self._mission_id[:12]}",
                daemon=True,
            )
            self._pending_thread.start()
            return self.status()

    def stop(self) -> dict[str, Any] | None:
        with self._lock:
            if self._mission_id is None:
                return None
            pending_thread = self._pending_thread
            self._pending_stop.set()
            self._pending_wakeup.set()

        if pending_thread is not None and pending_thread is not threading.current_thread():
            pending_thread.join(timeout=2)

        with self._lock:
            # A capture may finish before the telemetry sample after the last
            # detection arrives. Preserve that detection as an auditable
            # unsynchronized record instead of dropping it at shutdown.
            self._finalize_pending_locked()
            result = self.status()
            handle = self._artifact_handle
            if handle is not None:
                handle.flush()
                handle.close()
            self._mission_id = None
            self._artifact_handle = None
            self._artifact_path = None
            self._timeline.clear()
            self._pending.clear()
            self._seen_fingerprints.clear()
            self._latest_overlay = None
            self._pending_thread = None
            return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            latest = next(reversed(self._detections.values())) if self._detections else None
            return {
                "active": self._mission_id is not None,
                "mission_id": self._mission_id,
                "artifact_path": str(self._artifact_path) if self._artifact_path else None,
                "telemetry_timeline_samples": len(self._timeline),
                "accepted_detections": self._accepted,
                "rejected_detections": self._rejected,
                "pending_detections": len(self._pending),
                "latest_detection": copy.deepcopy(latest) if self._mission_id else None,
            }

    def record_telemetry(self, sample: TelemetrySample | Mapping[str, Any]) -> bool:
        """Observe a parsed MAVLink sample without blocking the receiver."""

        # Only hold the service lock long enough to snapshot the active
        # mission/timeline object. The pending worker may be flushing a JSONL
        # record while the receive-only MAVLink loop is delivering another
        # sample; coordinate computation and disk I/O stay in the worker
        # thread. Keeping the object reference also prevents a stop/start
        # race from appending an old sample to a newly started mission.
        with self._lock:
            active_mission_id = self._mission_id
            timeline = self._timeline
        if active_mission_id is None:
            return False
        sample_mission_id = (
            sample.mission_id if isinstance(sample, TelemetrySample) else sample.get("mission_id")
        )
        if sample_mission_id != active_mission_id:
            return False
        accepted = timeline.append(sample)
        if accepted:
            self._pending_wakeup.set()
        return accepted

    def flush_pending(self) -> int:
        """Drain resolvable pending events; useful for deterministic tests/tools."""

        with self._lock:
            return self._drain_pending_locked()

    def ingest_overlay(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Accept the existing Jetson overlay contract for diagnostics only.

        The web UI intentionally does not draw this bbox stream.  Detection
        events are the authoritative records for telemetry joining.
        """

        with self._lock:
            self._require_active()
            if not isinstance(payload, Mapping):
                raise VisionIngestError("overlay payload must be an object")
            self._validate_identity(payload)
            if payload.get("type") not in {"vision.frame_result", "vision.overlay"}:
                raise VisionIngestError("unsupported overlay type", code="INVALID_OVERLAY_TYPE")
            if payload.get("mission_id") != self._mission_id:
                raise VisionIngestError("overlay mission_id does not match active mission", code="MISSION_MISMATCH")
            self._latest_overlay = copy.deepcopy(dict(payload))
            return {
                "accepted": True,
                "mission_id": self._mission_id,
                "frame_id": payload["frame_id"],
                "detections": len(payload.get("detections") or []),
            }

    def ingest_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate, synchronize, and persist one Jetson detection event."""

        with self._lock:
            try:
                self._require_active()
                event = self._canonical_event(payload)
                detection_id = event["detection_id"]
                fingerprint = _event_fingerprint(event)
                known_fingerprint = self._seen_fingerprints.get(detection_id)
                if known_fingerprint is not None:
                    if known_fingerprint != fingerprint:
                        raise VisionIngestError(
                            "detection_id conflicts with an existing detection",
                            code="DETECTION_ID_CONFLICT",
                        )
                existing = self._detections.get(detection_id)
                if existing is not None:
                    return copy.deepcopy(existing)
                pending = self._pending.get(detection_id)
                if pending is not None:
                    return self._pending_view(pending)
                if known_fingerprint is not None:
                    return {
                        "schema_version": VISION_DETECTION_SCHEMA_VERSION,
                        "record_type": "detection_ack",
                        "source_record_type": event["source_record_type"],
                        "mission_id": event["mission_id"],
                        "detection_id": detection_id,
                        "duplicate": True,
                        "processing_status": "duplicate",
                    }

                result = self._process_event_locked(event)
                self._seen_fingerprints[detection_id] = fingerprint
                return result
            except VisionIngestError:
                self._rejected += 1
                raise

    def latest(self) -> dict[str, Any]:
        with self._lock:
            latest = (
                next(reversed(self._detections.values()))
                if self._mission_id and self._detections
                else None
            )
            return {
                "ok": True,
                "active": self._mission_id is not None,
                "mission_id": self._mission_id,
                "detection": copy.deepcopy(latest),
                "coordinate": copy.deepcopy(latest.get("coordinate")) if latest else None,
                "latest_overlay": copy.deepcopy(self._latest_overlay),
            }

    def _require_active(self) -> None:
        if self._mission_id is None:
            raise VisionIngestError(
                "no active recording mission",
                code="MISSION_NOT_ACTIVE",
            )

    def _pending_loop(self) -> None:
        while not self._pending_stop.wait(0.1):
            if not self._pending_wakeup.wait(0.5):
                continue
            self._pending_wakeup.clear()
            with self._lock:
                if self._mission_id is None:
                    return
                self._drain_pending_locked()

    def _process_event_locked(self, event: dict[str, Any]) -> dict[str, Any]:
        synchronized = self._synchronize(event)
        if synchronized["telemetry_sync_status"] != "synchronized":
            detection_id = event["detection_id"]
            self._pending[detection_id] = dict(event)
            self._pending.move_to_end(detection_id)
            while len(self._pending) > self.pending_detection_limit:
                _old_id, old_event = self._pending.popitem(last=False)
                self._persist_event_locked(
                    old_event,
                    self._synchronize(old_event),
                    processing_status="finalized_unsynchronized",
                )
            self._pending_wakeup.set()
            return self._pending_view(event, synchronized=synchronized)
        return self._persist_event_locked(
            event,
            synchronized,
            processing_status="resolved",
        )

    def _drain_pending_locked(self) -> int:
        resolved = 0
        for detection_id, event in list(self._pending.items()):
            synchronized = self._synchronize(event)
            if synchronized["telemetry_sync_status"] != "synchronized":
                continue
            self._pending.pop(detection_id, None)
            self._persist_event_locked(
                event,
                synchronized,
                processing_status="resolved",
            )
            resolved += 1
        return resolved

    def _finalize_pending_locked(self) -> None:
        for detection_id, event in list(self._pending.items()):
            self._pending.pop(detection_id, None)
            self._persist_event_locked(
                event,
                self._synchronize(event),
                processing_status="finalized_unsynchronized",
            )

    def _persist_event_locked(
        self,
        event: dict[str, Any],
        synchronized: dict[str, Any],
        *,
        processing_status: str,
    ) -> dict[str, Any]:
        coordinate = self._coordinate(synchronized)
        synchronized["coordinate"] = coordinate
        synchronized["coordinate_status"] = coordinate["status"]
        synchronized["processing_status"] = processing_status
        # A live estimate is never a qualification claim.  A ground truth
        # target and validated calibration are still required.
        synchronized["qualification_status"] = "NON_QUALIFICATION"
        self._write_artifact(synchronized)
        detection_id = event["detection_id"]
        self._detections[detection_id] = copy.deepcopy(synchronized)
        while len(self._detections) > self.recent_detection_limit:
            self._detections.popitem(last=False)
        self._accepted += 1
        return copy.deepcopy(synchronized)

    def _pending_view(
        self,
        event: dict[str, Any],
        *,
        synchronized: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        output = synchronized or self._synchronize(event)
        coordinate = self._coordinate(output)
        output["coordinate"] = coordinate
        output["coordinate_status"] = coordinate["status"]
        output["processing_status"] = "pending_telemetry"
        output["qualification_status"] = "NON_QUALIFICATION"
        return copy.deepcopy(output)

    def _canonical_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise VisionIngestError("detection payload must be an object")
        if payload.get("type") != "vision.detection_event":
            raise VisionIngestError("unsupported detection type", code="INVALID_DETECTION_TYPE")

        self._validate_identity(payload)
        mission_id = payload["mission_id"]
        if mission_id != self._mission_id:
            raise VisionIngestError(
                "detection mission_id does not match active mission",
                code="MISSION_MISMATCH",
            )

        detection_id = payload.get("detection_id")
        if not isinstance(detection_id, str) or not detection_id.strip():
            raise VisionIngestError("detection_id is required", code="DETECTION_ID_REQUIRED")
        if len(detection_id) > _MAX_DETECTION_ID_LENGTH:
            raise VisionIngestError("detection_id is too long", code="DETECTION_ID_INVALID")

        class_name = payload.get("class_name", payload.get("class"))
        if not isinstance(class_name, str) or not class_name.strip():
            raise VisionIngestError("class/class_name is required", code="CLASS_REQUIRED")
        class_id = payload.get("class_id")
        if class_id is None:
            raise VisionIngestError("class_id is required", code="CLASS_ID_REQUIRED")
        if (
            not isinstance(class_id, int) or isinstance(class_id, bool) or class_id < 0
        ):
            raise VisionIngestError("class_id is invalid", code="CLASS_ID_INVALID")

        confidence = payload.get("confidence")
        if not _finite_number(confidence) or not 0 <= float(confidence) <= 1:
            raise VisionIngestError("confidence must be between 0 and 1", code="CONFIDENCE_INVALID")

        bbox_value = None
        for key in ("bbox_normalized_xyxy", "bbox_xyxy_normalized", "bbox_norm_highres", "bbox"):
            if key in payload:
                bbox_value = payload[key]
                break
        bbox = _normalized_bbox(bbox_value)

        source_pts_ns = payload.get("source_pts_ns")
        if source_pts_ns is not None and (
            not isinstance(source_pts_ns, int)
            or isinstance(source_pts_ns, bool)
            or source_pts_ns < 0
        ):
            raise VisionIngestError("source_pts_ns is invalid", code="SOURCE_PTS_INVALID")

        return {
            "schema_version": VISION_DETECTION_SCHEMA_VERSION,
            "record_type": "detection",
            "source_record_type": payload.get("type"),
            "mission_id": mission_id,
            "capture_epoch": payload["capture_epoch"],
            "frame_id": payload["frame_id"],
            "camera_id": payload["camera_id"],
            "capture_utc_ns": payload["capture_utc_ns"],
            "source_pts_ns": source_pts_ns,
            "detection_id": detection_id.strip(),
            "class_id": class_id,
            "class_name": class_name.strip(),
            "confidence": float(confidence),
            # ``bbox`` is the canonical normalized master-image XYXY contract.
            "bbox": bbox,
            "bbox_xyxy_normalized": bbox,
        }

    def _synchronize(self, event: dict[str, Any]) -> dict[str, Any]:
        output = dict(event)
        try:
            telemetry = self._timeline.interpolate(event["capture_utc_ns"])
            if any(telemetry.get(field) is None for field in REQUIRED_TELEMETRY_FIELDS):
                raise SynchronizationError("interpolated telemetry state is incomplete")
        except SynchronizationError as exc:
            telemetry = {
                field: None
                for field in REQUIRED_TELEMETRY_FIELDS
            }
            telemetry.update(
                {
                    "interpolation": "unavailable",
                    "source_timestamp_before": None,
                    "source_timestamp_after": None,
                    "interpolation_alpha": None,
                }
            )
            output["telemetry_sync_status"] = "unsynchronized"
            output["telemetry_sync_error"] = str(exc)
        else:
            output["telemetry_sync_status"] = "synchronized"

        output["telemetry"] = telemetry
        output["latitude"] = telemetry.get("latitude")
        output["longitude"] = telemetry.get("longitude")
        output["altitude"] = telemetry.get("altitude")
        output["roll"] = telemetry.get("roll_deg")
        output["pitch"] = telemetry.get("pitch_deg")
        output["yaw"] = telemetry.get("yaw_deg")
        return output

    def _coordinate(self, synchronized: dict[str, Any]) -> dict[str, Any]:
        if synchronized.get("telemetry_sync_status") != "synchronized":
            return _unavailable_coordinate(
                synchronized,
                "TELEMETRY_NOT_SYNCHRONIZED",
                "coordinate reconstruction requires a complete source-time telemetry bracket",
            )
        if not self.coordinate_enabled:
            return _unavailable_coordinate(
                synchronized,
                "COORDINATE_RECONSTRUCTION_DISABLED",
                "coordinate reconstruction is disabled until explicit calibration/AGL configuration is provided",
            )
        try:
            return self.coordinate_adapter.reconstruct(
                synchronized,
                altitude_reference=self.altitude_reference,
                camera_attitude_frame=self.camera_attitude_frame,
            )
        except Exception as exc:  # Optional coordinate work must not break capture.
            return _unavailable_coordinate(
                synchronized,
                "COORDINATE_RECONSTRUCTION_FAILED",
                str(exc),
            )

    def _write_artifact(self, record: dict[str, Any]) -> None:
        if self._artifact_handle is None:
            return
        self._artifact_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._artifact_handle.flush()

    @staticmethod
    def _validate_identity(payload: Mapping[str, Any]) -> None:
        mission_id = payload.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise VisionIngestError("mission_id is required", code="MISSION_ID_REQUIRED")

        for field, minimum in (("capture_epoch", 1), ("frame_id", 0)):
            value = payload.get(field)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < minimum
            ):
                raise VisionIngestError(f"{field} is invalid", code="FRAME_IDENTITY_INVALID")

        capture_utc_ns = payload.get("capture_utc_ns")
        if (
            not isinstance(capture_utc_ns, int)
            or isinstance(capture_utc_ns, bool)
            or capture_utc_ns <= 0
        ):
            raise VisionIngestError(
                "capture_utc_ns must be a positive source timestamp",
                code="CAPTURE_TIMESTAMP_INVALID",
            )

        camera_id = payload.get("camera_id")
        if not isinstance(camera_id, str) or not camera_id.strip():
            raise VisionIngestError("camera_id is required", code="CAMERA_ID_REQUIRED")


def _normalized_bbox(value: Any) -> list[float]:
    if isinstance(value, Mapping):
        value = value.get("xyxy_normalized", value.get("bbox_normalized_xyxy"))
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise VisionIngestError(
            "bbox must be a four-element normalized XYXY array",
            code="BBOX_INVALID",
        )
    bbox = [float(item) if _finite_number(item) else math.nan for item in value]
    if (
        any(not math.isfinite(item) or item < 0 or item > 1 for item in bbox)
        or bbox[0] >= bbox[2]
        or bbox[1] >= bbox[3]
    ):
        raise VisionIngestError(
            "bbox coordinates must be normalized XYXY values in [0, 1] with positive area",
            code="BBOX_INVALID",
        )
    return bbox


def _event_fingerprint(event: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        event.get("mission_id"),
        event.get("capture_epoch"),
        event.get("frame_id"),
        event.get("camera_id"),
        event.get("capture_utc_ns"),
        event.get("source_pts_ns"),
        event.get("class_id"),
        event.get("class_name"),
        event.get("confidence"),
        tuple(event.get("bbox", ())),
    )


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _unavailable_coordinate(record: Mapping[str, Any], code: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "coordinate_estimate",
        "status": NOT_AVAILABLE,
        "error_code": code,
        "reason": reason,
        "mission_id": record.get("mission_id"),
        "detection_id": record.get("detection_id"),
        "capture_epoch": record.get("capture_epoch"),
        "frame_id": record.get("frame_id"),
        "capture_utc_ns": record.get("capture_utc_ns"),
        "latitude": None,
        "longitude": None,
        "local_offset_east_m": None,
        "local_offset_north_m": None,
        "distance_m": None,
        "bearing_deg": None,
        "pixel_center": None,
        "bbox_xyxy_normalized": record.get("bbox_xyxy_normalized"),
        "altitude_reference": None,
        "altitude_m": None,
        "calibration_validated": False,
    }


def is_bearer_token_valid(authorization: str | None, expected_token: str) -> bool:
    """Constant-time validation helper used by the HTTP route."""

    if not expected_token or not authorization:
        return False
    scheme, separator, token = authorization.partition(" ")
    return bool(
        separator
        and scheme.lower() == "bearer"
        and hmac.compare_digest(token.strip(), expected_token)
    )
