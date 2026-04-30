from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from time import time
from typing import Any


@dataclass
class SessionLogSummary:
    session_id: str
    start_time: float
    end_time: float | None = None
    system_address: str = "-"
    command_count: int = 0
    telemetry_count: int = 0
    event_count: int = 0
    last_error: str | None = None
    last_event_type: str | None = None
    log_path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class SessionLogStore:
    def __init__(self, log_dir: str | Path | None = None, session_id: str | None = None, system_address: str = "-"):
        base_dir = Path(log_dir or os.getenv("SESSION_LOG_DIR") or Path(__file__).resolve().parents[2] / "runtime" / "logs")
        base_dir.mkdir(parents=True, exist_ok=True)

        self.log_dir = base_dir
        self.session_id = session_id or f"{time():.0f}-{uuid.uuid4().hex[:8]}"
        self.path = self.log_dir / f"{self.session_id}.jsonl"
        self._lock = threading.Lock()
        self._summary = SessionLogSummary(
            session_id=self.session_id,
            start_time=time(),
            system_address=system_address,
            log_path=str(self.path),
        )
        self.record_event("session_start", message="Session started", system_address=system_address)

    def record_event(self, event_type: str, message: str | None = None, **data: Any) -> dict:
        entry = {
            "ts": time(),
            "type": event_type,
            "session_id": self.session_id,
        }
        if message is not None:
            entry["message"] = message

        for key, value in data.items():
            if value is not None:
                entry[key] = value

        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

            self._summary.event_count += 1
            self._summary.last_event_type = event_type
            if event_type == "telemetry":
                self._summary.telemetry_count += 1
            if event_type.startswith("command_"):
                self._summary.command_count += 1
            if event_type in {"command_error", "connection_error", "session_end"}:
                self._summary.last_error = entry.get("error") or entry.get("message")

        return entry

    def record_command(self, command: str, ok: bool, message: str | None = None, error: str | None = None, error_code: str | None = None, **data: Any) -> dict:
        event_type = "command_success" if ok else "command_error"
        payload = {"command": command, "ok": ok, **data}
        if error_code is not None:
            payload["error_code"] = error_code
        if error is not None:
            payload["error"] = error
        return self.record_event(event_type, message=message, **payload)

    def record_telemetry(self, telemetry_state: Any) -> dict:
        if hasattr(telemetry_state, "to_dict"):
            payload = telemetry_state.to_dict()
        elif isinstance(telemetry_state, dict):
            payload = dict(telemetry_state)
        else:
            payload = {"value": str(telemetry_state)}

        snapshot = {
            "connected": payload.get("connected"),
            "lat": payload.get("lat"),
            "lng": payload.get("lng"),
            "alt": payload.get("alt"),
            "alt_amsl": payload.get("alt_amsl"),
            "armed": payload.get("armed"),
            "flight_mode": payload.get("flight_mode"),
            "battery_percent": payload.get("battery_percent"),
            "last_update": payload.get("last_update"),
            "error": payload.get("error"),
            "source": payload.get("source"),
            "system_address": payload.get("system_address"),
        }
        return self.record_event("telemetry", data=snapshot)

    def close_session(self, reason: str | None = None) -> dict:
        if self._summary.end_time is None:
            self._summary.end_time = time()
        return self.record_event("session_end", message=reason or "Session closed", end_time=self._summary.end_time)

    def summary(self) -> dict:
        with self._lock:
            return self._summary.to_dict()

    def recent_events(self, limit: int = 50) -> list[dict]:
        if limit <= 0:
            return []

        if not self.path.exists():
            return []

        with self._lock:
            with self.path.open("r", encoding="utf-8") as handle:
                events = [json.loads(line) for line in handle if line.strip()]
        return events[-limit:]