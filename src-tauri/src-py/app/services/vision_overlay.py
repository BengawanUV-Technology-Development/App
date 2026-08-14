from __future__ import annotations

import copy
import math
import os
import threading
import time
from numbers import Real
from typing import Any


from app.services.geotagging import estimate_target_gps

class VisionOverlayError(ValueError):
    """Raised when a per-frame vision overlay does not match the contract."""


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise VisionOverlayError(f"{field} must be a finite number")
    return float(value)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VisionOverlayError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VisionOverlayError(f"{field} must be a non-negative integer")
    return value


def _bbox(value: Any, width: int, height: int, field: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise VisionOverlayError(f"{field} must contain four coordinates")
    coordinates = [_number(item, f"{field}[{index}]") for index, item in enumerate(value)]
    x1, y1, x2, y2 = coordinates
    if x2 <= x1 or y2 <= y1:
        raise VisionOverlayError(f"{field} must have positive area")
    if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        raise VisionOverlayError(f"{field} must fit within {width}x{height}")
    return coordinates


class VisionOverlayStore:
    """Keep the latest detector result for the live low-resolution preview.

    This is intentionally separate from the event-level detection endpoint.
    A detector can publish one payload per frame without invoking the priority
    agent or dispatchers. The store expires quickly so an old box cannot remain
    over a stopped or disconnected video stream.
    """

    def __init__(self, ttl_seconds: float | None = None):
        if ttl_seconds is None:
            raw_ttl = os.getenv("DETECTION_OVERLAY_TTL_SECONDS", "1.0")
            try:
                ttl_seconds = float(raw_ttl)
            except ValueError as exc:
                raise VisionOverlayError("DETECTION_OVERLAY_TTL_SECONDS must be a number") from exc
        if not 0.1 <= ttl_seconds <= 30:
            raise VisionOverlayError("DETECTION_OVERLAY_TTL_SECONDS must be between 0.1 and 30")

        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._latest: dict[str, Any] | None = None
        self._received_at_unix: float | None = None
        self._received_monotonic: float | None = None

    @staticmethod
    def _normalize(payload: Any, telemetry: dict | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise VisionOverlayError("overlay payload must be a JSON object")
        if payload.get("type") != "vision.overlay":
            raise VisionOverlayError("overlay payload type must be vision.overlay")

        frame_id = _non_negative_int(payload.get("frame_id"), "frame_id")
        source_width = _positive_int(payload.get("source_width"), "source_width")
        source_height = _positive_int(payload.get("source_height"), "source_height")
        network_width = _positive_int(payload.get("network_width"), "network_width")
        network_height = _positive_int(payload.get("network_height"), "network_height")

        detections = payload.get("detections")
        if not isinstance(detections, list):
            raise VisionOverlayError("detections must be an array")
        if len(detections) > 512:
            raise VisionOverlayError("detections cannot contain more than 512 items")

        normalized_detections = []
        for index, detection in enumerate(detections):
            if not isinstance(detection, dict):
                raise VisionOverlayError(f"detections[{index}] must be an object")
            label = detection.get("class")
            if not isinstance(label, str) or not label.strip():
                raise VisionOverlayError(f"detections[{index}].class must be a non-empty string")
            confidence = _number(detection.get("confidence"), f"detections[{index}].confidence")
            if not 0 <= confidence <= 1:
                raise VisionOverlayError(f"detections[{index}].confidence must be between 0 and 1")

            normalized = {
                "class": label.strip(),
                "confidence": confidence,
                "bbox_network": _bbox(
                    detection.get("bbox_network"),
                    network_width,
                    network_height,
                    f"detections[{index}].bbox_network",
                ),
            }
            if detection.get("bbox_highres") is not None:
                normalized["bbox_highres"] = _bbox(
                    detection["bbox_highres"],
                    source_width,
                    source_height,
                    f"detections[{index}].bbox_highres",
                )
            if detection.get("bbox_norm_highres") is not None:
                normalized_bbox = detection["bbox_norm_highres"]
                if not isinstance(normalized_bbox, (list, tuple)) or len(normalized_bbox) != 4:
                    raise VisionOverlayError(
                        f"detections[{index}].bbox_norm_highres must contain four coordinates"
                    )
                normalized_values = [
                    _number(item, f"detections[{index}].bbox_norm_highres[{coord}]")
                    for coord, item in enumerate(normalized_bbox)
                ]
                if any(value < 0 or value > 1 for value in normalized_values):
                    raise VisionOverlayError(
                        f"detections[{index}].bbox_norm_highres must be between 0 and 1"
                    )
                normalized["bbox_norm_highres"] = normalized_values

            # --- GEOTAGGING INJECTION ---
            if telemetry and telemetry.get("gps_valid"):
                tel = telemetry.get("telemetry", {})
                lat = tel.get("lat")
                lng = tel.get("lng")
                alt_m = tel.get("relative_alt") # Use AGL
                roll = tel.get("roll_deg")
                pitch = tel.get("pitch_deg")
                yaw = tel.get("yaw_deg")
                
                if all(v is not None for v in [lat, lng, alt_m, roll, pitch, yaw]):
                    # Determine center of detection. Prefer highres, else network
                    if "bbox_highres" in normalized:
                        x1, y1, x2, y2 = normalized["bbox_highres"]
                        u_c, v_c = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                        img_w, img_h = source_width, source_height
                    else:
                        x1, y1, x2, y2 = normalized["bbox_network"]
                        u_c, v_c = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                        img_w, img_h = network_width, network_height
                        
                    gps = estimate_target_gps(
                        u_c, v_c, img_w, img_h,
                        lat, lng, alt_m, roll, pitch, yaw
                    )
                    if gps:
                        normalized["geotag_lat"] = gps[0]
                        normalized["geotag_lng"] = gps[1]
                        
            normalized_detections.append(normalized)

        detection_id = payload.get("detection_id")
        if detection_id is not None and not isinstance(detection_id, str):
            raise VisionOverlayError("detection_id must be a string when provided")

        session_id = payload.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise VisionOverlayError("session_id must be a string when provided")

        timestamp = payload.get("timestamp")
        if timestamp is not None and not isinstance(timestamp, str):
            raise VisionOverlayError("timestamp must be a string when provided")

        frame_timestamp = payload.get("frame_timestamp")
        if frame_timestamp is not None and not isinstance(frame_timestamp, str):
            raise VisionOverlayError("frame_timestamp must be a string when provided")

        pts_ns = payload.get("pts_ns")
        if pts_ns is not None:
            pts_ns = _non_negative_int(pts_ns, "pts_ns")

        camera_id = payload.get("camera_id", "b0249")
        if not isinstance(camera_id, str) or not camera_id.strip():
            raise VisionOverlayError("camera_id must be a non-empty string")
        preview_source = payload.get("preview_source_at_detection", "digital")
        if preview_source not in {"digital", "analog"}:
            raise VisionOverlayError("preview_source_at_detection must be digital or analog")
        overlay_compatible = payload.get("overlay_compatible", preview_source == "digital")
        if not isinstance(overlay_compatible, bool):
            raise VisionOverlayError("overlay_compatible must be a boolean")

        return {
            "schema_version": str(payload.get("schema_version") or "1.0"),
            "type": "vision.overlay",
            "session_id": session_id,
            "detection_id": detection_id,
            "timestamp": timestamp,
            "frame_id": frame_id,
            "frame_timestamp": frame_timestamp,
            "pts_ns": pts_ns,
            "camera_id": camera_id.strip(),
            "preview_source_at_detection": preview_source,
            "overlay_compatible": overlay_compatible,
            "source_width": source_width,
            "source_height": source_height,
            "network_width": network_width,
            "network_height": network_height,
            "detections": normalized_detections,
        }

    def ingest(self, payload: Any, telemetry: dict | None = None) -> dict[str, Any]:
        normalized = self._normalize(payload, telemetry)
        received_at_unix = time.time()
        received_monotonic = time.monotonic()
        with self._lock:
            self._latest = normalized
            self._received_at_unix = received_at_unix
            self._received_monotonic = received_monotonic
        return self.latest()

    def clear(self) -> None:
        """Discard live correlation state after a preview-source transition."""

        with self._lock:
            self._latest = None
            self._received_at_unix = None
            self._received_monotonic = None

    def latest(self) -> dict[str, Any]:
        with self._lock:
            if self._latest is None or self._received_monotonic is None:
                return {
                    "ok": True,
                    "stale": True,
                    "detections": [],
                    "frame_id": None,
                    "received_at_unix": None,
                    "age_seconds": None,
                }

            age_seconds = max(0.0, time.monotonic() - self._received_monotonic)
            stale = age_seconds > self.ttl_seconds
            response = copy.deepcopy(self._latest)
            if stale:
                response["detections"] = []
            response.update(
                ok=True,
                stale=stale,
                received_at_unix=self._received_at_unix,
                age_seconds=round(age_seconds, 3),
            )
            return response
