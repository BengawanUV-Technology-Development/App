"""Mission-scoped, versioned telemetry JSONL writer."""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import threading
import uuid
from pathlib import Path
from time import monotonic_ns, time_ns
from typing import Any

from app.config import MISSION_LOG_SCHEMA_VERSION
from app.models import TelemetrySample


# The Jetson recording agent persists the shared mission identity and accepts
# only ``mission-<uuid>``. Keep Ground-generated IDs in that same contract so
# the telemetry JSONL and Jetson evidence directory can always be joined.
_JETSON_MISSION_ID = re.compile(
    r"^mission-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class MissionTelemetryError(RuntimeError):
    """Raised when a mission telemetry lifecycle operation is invalid."""


class MissionTelemetryRecorder:
    """Write canonical samples without blocking the UDP receiver on disk I/O."""

    def __init__(
        self,
        log_dir: str | Path | None = None,
        schema_version: int = MISSION_LOG_SCHEMA_VERSION,
        queue_size: int = 2_000,
    ) -> None:
        base_dir = Path(
            log_dir
            or os.getenv("MISSION_LOG_DIR")
            or os.getenv("SESSION_LOG_DIR")
            or (Path.home() / ".local" / "share" / "BengawanUV" / "missions")
        )
        self.log_dir = base_dir / "missions"
        self.schema_version = schema_version
        self.queue_size = queue_size

        self._lock = threading.RLock()
        self._mission_id: str | None = None
        self._path: Path | None = None
        self._queue: queue.Queue[dict[str, Any] | None] | None = None
        self._writer_thread: threading.Thread | None = None
        self._dropped_samples = 0
        self._started_at_ns: int | None = None
        self._last_completed: dict[str, Any] | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._mission_id is not None

    @property
    def mission_id(self) -> str | None:
        with self._lock:
            return self._mission_id

    @property
    def path(self) -> Path | None:
        with self._lock:
            return self._path

    @property
    def dropped_samples(self) -> int:
        with self._lock:
            return self._dropped_samples

    def start(self, mission_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._mission_id is not None:
                raise MissionTelemetryError(
                    f"mission {self._mission_id} is already recording"
                )

            mission_id = self._safe_mission_id(mission_id)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            mission_dir = self.log_dir / mission_id
            path = mission_dir / "telemetry.jsonl"
            event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
                maxsize=self.queue_size
            )
            try:
                mission_dir.mkdir(parents=False, exist_ok=False)
                handle = path.open("x", encoding="utf-8")
            except FileExistsError as exc:
                raise MissionTelemetryError(
                    f"mission telemetry already exists: {path}"
                ) from exc
            writer = threading.Thread(
                target=self._writer_loop,
                args=(handle, event_queue),
                name=f"mission-telemetry-{mission_id[:12]}",
                daemon=True,
            )

            self._mission_id = mission_id
            self._path = path
            self._queue = event_queue
            self._writer_thread = writer
            self._dropped_samples = 0
            self._started_at_ns = time_ns()
            writer.start()

            self._enqueue_locked(
                self._event(
                    message_type="MISSION_START",
                    payload={"started_at_ns": self._started_at_ns},
                )
            )
            return self.status()

    def record_sample(self, sample: TelemetrySample) -> bool:
        with self._lock:
            if self._mission_id is None or self._queue is None:
                return False

            entry = sample.to_dict()
            entry["schema_version"] = self.schema_version
            entry["mission_id"] = self._mission_id
            entry["record_type"] = "telemetry_sample"
            self._enqueue_locked(entry)
            return True

    def record_raw_packet(
        self,
        packet: bytes,
        receive_timestamp: int,
        receive_monotonic_ns: int,
    ) -> bool:
        """Optionally persist raw bytes as a debug-only JSONL record."""

        with self._lock:
            if self._mission_id is None or self._queue is None:
                return False
            entry = self._event(
                message_type="RAW_MAVLINK",
                payload={
                    "encoding": "base64",
                    "packet": base64.b64encode(packet).decode("ascii"),
                },
                receive_timestamp=receive_timestamp,
                receive_monotonic_ns=receive_monotonic_ns,
            )
            entry["record_type"] = "raw_mavlink"
            self._enqueue_locked(entry)
            return True

    def stop(self, reason: str = "completed") -> dict[str, Any] | None:
        with self._lock:
            if self._mission_id is None or self._queue is None:
                return None

            mission_id = self._mission_id
            path = self._path
            writer = self._writer_thread
            event_queue = self._queue
            stopped_at_ns = time_ns()

            # Stop is allowed to block briefly so the end marker is durable;
            # normal samples use put_nowait and never block recvfrom().
            event_queue.put(
                self._event(
                    message_type="MISSION_END",
                    payload={"reason": reason, "stopped_at_ns": stopped_at_ns},
                )
            )
            event_queue.put(None)
            self._mission_id = None
            self._path = None
            self._queue = None
            self._writer_thread = None
            self._started_at_ns = None

        result = {
            "mission_id": mission_id,
            "path": str(path) if path else None,
            "stopped_at_ns": stopped_at_ns,
            "dropped_samples": self.dropped_samples,
        }
        with self._lock:
            self._last_completed = dict(result)

        if writer is not None:
            writer.join(timeout=5)

        return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "recording": self._mission_id is not None,
                "mission_id": self._mission_id,
                "telemetry_log_path": str(self._path) if self._path else None,
                "telemetry_log_schema_version": self.schema_version,
                "telemetry_dropped_samples": self._dropped_samples,
                "mission_started_at_ns": self._started_at_ns,
                "last_completed": dict(self._last_completed)
                if self._last_completed
                else None,
            }

    def _enqueue_locked(self, entry: dict[str, Any]) -> None:
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(entry)
        except queue.Full:
            self._dropped_samples += 1

    def _event(
        self,
        message_type: str,
        payload: dict[str, Any],
        receive_timestamp: int | None = None,
        receive_monotonic_ns: int | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_type": "mission_event",
            "mission_id": self._mission_id,
            "source_timestamp": None,
            "source_timestamp_raw": None,
            "source_clock_domain": None,
            "receive_timestamp": receive_timestamp or time_ns(),
            "receive_monotonic_ns": receive_monotonic_ns or monotonic_ns(),
            "source_time_valid": False,
            "message_type": message_type,
            "system_id": None,
            "component_id": None,
            "payload": payload,
        }

    @staticmethod
    def _safe_mission_id(value: str | None) -> str:
        if value and _JETSON_MISSION_ID.fullmatch(value):
            return value
        return f"mission-{uuid.uuid4()}"

    @staticmethod
    def _writer_loop(handle, event_queue: queue.Queue[dict[str, Any] | None]) -> None:
        try:
            while True:
                entry = event_queue.get()
                try:
                    if entry is None:
                        return
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    handle.flush()
                finally:
                    event_queue.task_done()
        finally:
            handle.flush()
            handle.close()
