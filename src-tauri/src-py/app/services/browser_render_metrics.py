"""Deduplicated browser render timing samples keyed by canonical frame identity."""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from numbers import Real
from typing import Any

from .frame_sync import CanonicalKey, FrameSyncError
from .latency_metrics import LatencyMetrics


class BrowserRenderMetricsError(ValueError):
    pass


class BrowserRenderMetrics:
    def __init__(self, capacity: int = 4096):
        self._lock = threading.RLock()
        self._seen: OrderedDict[tuple[str, int, int, str], None] = OrderedDict()
        self._capacity = capacity
        self._transport_to_render = LatencyMetrics(capacity)
        self._duplicate_count = 0

    def record(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("schema_version") != "2.0":
            raise BrowserRenderMetricsError("browser render metric must use schema_version 2.0")
        try:
            key = CanonicalKey.from_payload(payload)
        except FrameSyncError as exc:
            raise BrowserRenderMetricsError("browser render metric has invalid identity") from exc

        value = payload.get("receive_to_render_ms")
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
            raise BrowserRenderMetricsError("receive_to_render_ms must be finite")
        value = float(value)
        if value < 0 or value > 60_000:
            raise BrowserRenderMetricsError("receive_to_render_ms must be between 0 and 60000")

        identity = (key.mission_id, key.capture_epoch, key.frame_id, key.camera_id)
        with self._lock:
            if identity in self._seen:
                self._duplicate_count += 1
                return {"accepted": False, "duplicate": True, **self.snapshot()}
            self._seen[identity] = None
            while len(self._seen) > self._capacity:
                self._seen.popitem(last=False)
            self._transport_to_render.observe(value)
        return {"accepted": True, "duplicate": False, **self.snapshot()}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "receive_to_render": self._transport_to_render.snapshot(),
                "duplicate_count": self._duplicate_count,
                "identity_window": len(self._seen),
            }
