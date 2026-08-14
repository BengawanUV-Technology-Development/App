"""Bounded in-memory buffer of recent per-detection map dots for the LIVE
(in-flight) map view.

Deliberately ephemeral and un-clustered: every raw detection the Jetson
reports gets its own dot here, opacity-coded by confidence, so an operator
can see detection density/noise in real time while a flight is in progress.
Narrowing that noise down to a confirmed location is the post-flight
snapshot pipeline's job (see docs/post-flight-detection-snapshots.md) --
this store is not persisted and is reset at the start of every recording.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

_LOCATED_STATUSES = {"ESTIMATED", "ESTIMATED_UNCALIBRATED"}


class LiveDetectionStore:
    def __init__(self, max_age_seconds: float = 20.0, capacity: int = 500):
        self.max_age_seconds = max_age_seconds
        self.capacity = capacity
        self._lock = threading.Lock()
        self._items: deque[dict[str, Any]] = deque(maxlen=capacity)

    def add_many(
        self,
        detections: list[dict[str, Any]],
        *,
        capture_utc_ns: int | None,
        fallback_lat: float | None,
        fallback_lon: float | None,
        now: float | None = None,
    ) -> None:
        """Record one dot per detection. Detections with a real ground-plane
        estimate ("located") use that lat/lon; detections without one (no
        telemetry within the join window, ray doesn't hit the ground, etc.)
        fall back to the vehicle's own current position -- "a detection just
        happened near here" -- rendered distinctly (dim gray) on the frontend
        rather than dropped, per team decision. If even the vehicle position
        is unknown yet, the detection is skipped: there is nothing to plot.
        """
        now = now if now is not None else time.time()
        with self._lock:
            for detection in detections:
                coordinate = detection.get("coordinate") or {}
                located = coordinate.get("status") in _LOCATED_STATUSES
                lat = coordinate.get("lat") if located else fallback_lat
                lon = coordinate.get("lon") if located else fallback_lon
                if lat is None or lon is None:
                    continue
                self._items.append(
                    {
                        "detection_id": detection.get("detection_id"),
                        "class": detection.get("class"),
                        "confidence": detection.get("confidence"),
                        "located": located,
                        "lat": lat,
                        "lon": lon,
                        "capture_utc_ns": capture_utc_ns,
                        "received_at_unix": now,
                    }
                )

    def snapshot(self) -> list[dict[str, Any]]:
        cutoff = time.time() - self.max_age_seconds
        with self._lock:
            return [item for item in self._items if item["received_at_unix"] >= cutoff]

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
