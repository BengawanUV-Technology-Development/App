"""Ground-side telemetry history: persists Mission Planner snapshots and
serves a bounded, timestamp-indexed buffer so other consumers (e.g. target
coordinate estimation) can look up "what was the vehicle's pose near this
detection's capture time" instead of only ever seeing the latest sample.

This is the ground counterpart to the Jetson's onboard telemetry.jsonl
(jetson/mavlink_telemetry.py) -- that file only exists on the vehicle and is
never sent up here. The Jetson and this recorder are two independent MAVLink
readers (onboard wired link vs. Mission Planner's ground radio downlink);
see docs/PROJECT_CONTEXT for the rationale. Nothing in this module changes
that -- it just makes the ground-side stream persistent and queryable.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class TelemetryRecorder:
    """Append-only JSONL log plus an in-memory ring buffer for nearest-time lookups."""

    def __init__(self, log_path: str | Path | None = None, history_size: int = 600):
        path = log_path or os.getenv("BUV_GROUND_TELEMETRY_LOG") or "runtime/ground_telemetry.jsonl"
        self.log_path = Path(path).resolve()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._history: deque[tuple[float, dict[str, Any]]] = deque(maxlen=history_size)
        self._lock = threading.Lock()
        self._file = self.log_path.open("a", encoding="utf-8", buffering=1)

    def record(self, telemetry: dict[str, Any], now: float | None = None) -> None:
        """Store one successfully-polled telemetry sample (skip stale/offline snapshots)."""
        now = now if now is not None else time.time()
        row = {"recorded_at_unix": now, **telemetry}
        with self._lock:
            self._history.append((now, telemetry))
            self._file.write(json.dumps(row, separators=(",", ":")) + "\n")

    def nearest(self, target_unix: float, max_age_seconds: float = 0.5) -> dict[str, Any] | None:
        """Return the telemetry sample closest to target_unix, or None if none is within tolerance."""
        with self._lock:
            history = list(self._history)
        if not history:
            return None
        best_ts, best_telemetry = min(history, key=lambda item: abs(item[0] - target_unix))
        age = abs(best_ts - target_unix)
        if age > max_age_seconds:
            return None
        return {**best_telemetry, "_sample_age_seconds": age, "_sample_unix": best_ts}

    def close(self) -> None:
        with self._lock:
            self._file.close()


DEFAULT_JOIN_WINDOW_SECONDS = _env_float("BUV_TELEMETRY_JOIN_WINDOW_SECONDS", 0.5)
