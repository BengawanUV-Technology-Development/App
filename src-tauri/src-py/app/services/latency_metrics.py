"""Bounded latency samples for operational health and qualification evidence."""

from __future__ import annotations

import threading
from collections import deque
from numbers import Real


class LatencyMetrics:
    """Keep a bounded sample window and expose stable percentile snapshots."""

    def __init__(self, capacity: int = 4096):
        if not isinstance(capacity, int) or capacity < 2:
            raise ValueError("latency metric capacity must be at least two")
        self.capacity = capacity
        self._lock = threading.RLock()
        self._samples: deque[float] = deque(maxlen=capacity)

    def observe(self, value_ms: Real) -> None:
        value = float(value_ms)
        if value != value or value < 0 or value == float("inf"):
            raise ValueError("latency sample must be a finite non-negative number")
        with self._lock:
            self._samples.append(value)

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()

    def snapshot(self) -> dict[str, float | int | None]:
        with self._lock:
            values = sorted(self._samples)
        if not values:
            return {
                "count": 0,
                "last_ms": None,
                "min_ms": None,
                "max_ms": None,
                "p50_ms": None,
                "p95_ms": None,
            }

        def percentile(rank: float) -> float:
            position = (len(values) - 1) * rank
            lower = int(position)
            upper = min(lower + 1, len(values) - 1)
            fraction = position - lower
            return values[lower] + (values[upper] - values[lower]) * fraction

        with self._lock:
            last = self._samples[-1]
        return {
            "count": len(values),
            "last_ms": round(last, 3),
            "min_ms": round(values[0], 3),
            "max_ms": round(values[-1], 3),
            "p50_ms": round(percentile(0.50), 3),
            "p95_ms": round(percentile(0.95), 3),
        }
