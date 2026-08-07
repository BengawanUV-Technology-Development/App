from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


class JetsonRecordingError(RuntimeError):
    """Raised when the GCS cannot control the Jetson recording agent."""


class JetsonRecordingClient:
    """Small HTTP client for the recorder agent running on the Jetson.

    The browser never calls the Jetson directly. The GCS backend uses this
    client over the private Tailscale network and keeps the existing recording
    API stable for the frontend.
    """

    def __init__(self):
        self.base_url = os.getenv("JETSON_RECORDING_AGENT_URL", "").strip().rstrip("/")
        self.token = os.getenv("JETSON_RECORDING_AGENT_TOKEN", "").strip()
        raw_timeout = os.getenv("JETSON_RECORDING_AGENT_TIMEOUT_SECONDS", "1.0")
        try:
            self.timeout = float(raw_timeout)
        except ValueError as exc:
            raise JetsonRecordingError(
                "JETSON_RECORDING_AGENT_TIMEOUT_SECONDS must be a number"
            ) from exc
        if not 0.1 <= self.timeout <= 10:
            raise JetsonRecordingError(
                "JETSON_RECORDING_AGENT_TIMEOUT_SECONDS must be between 0.1 and 10"
            )

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _request(self, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict:
        if not self.configured:
            raise JetsonRecordingError(
                "JETSON_RECORDING_AGENT_URL is not configured; high-res recording is unavailable"
            )

        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw_response = response.read()
                status = response.status
        except (OSError, URLError) as exc:
            raise JetsonRecordingError(f"Jetson recording agent unavailable: {exc}") from exc

        try:
            result = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JetsonRecordingError("Jetson recording agent returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise JetsonRecordingError("Jetson recording agent returned a non-object response")
        if status >= 300 or result.get("ok") is False:
            raise JetsonRecordingError(str(result.get("error") or f"HTTP {status}"))
        return result

    def status(self) -> dict:
        if not self.configured:
            return {
                "ok": False,
                "recording": False,
                "status": "REMOTE_UNCONFIGURED",
                "session_id": None,
                "session_dir": None,
                "started_at": None,
                "ended_at": None,
                "frame_count": 0,
                "duration_seconds": 0,
                "error": "JETSON_RECORDING_AGENT_URL is not configured",
            }
        try:
            return self._request("/recording/status")
        except JetsonRecordingError as exc:
            return {
                "ok": False,
                "recording": False,
                "status": "REMOTE_OFFLINE",
                "session_id": None,
                "session_dir": None,
                "started_at": None,
                "ended_at": None,
                "frame_count": 0,
                "duration_seconds": 0,
                "error": str(exc),
            }

    def start(self, label: str | None = None) -> dict:
        return self._request("/recording/start", "POST", {"label": label})

    def stop(self) -> dict:
        return self._request("/recording/stop", "POST")
