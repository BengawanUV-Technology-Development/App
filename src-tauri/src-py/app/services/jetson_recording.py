"""Authenticated control client for the Jetson recording agent."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class JetsonRecordingError(RuntimeError):
    """Raised when the Jetson recording agent cannot be reached or rejects a request."""


class JetsonRecordingClient:
    def __init__(self, base_url: str, token: str, timeout: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        if not self.configured:
            raise JetsonRecordingError(
                "Jetson recording agent is not configured; set "
                "JETSON_RECORDING_AGENT_TOKEN"
            )

        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                detail = None
            message = detail.get("error") if isinstance(detail, dict) else None
            raise JetsonRecordingError(
                message or f"Jetson recording agent returned HTTP {exc.code}"
            ) from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise JetsonRecordingError(f"Jetson recording agent unavailable: {exc}") from exc

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JetsonRecordingError("Jetson recording agent returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise JetsonRecordingError("Jetson recording agent returned a non-object response")
        if result.get("ok") is False:
            raise JetsonRecordingError(str(result.get("error") or "Jetson request failed"))
        return result

    def status(self) -> dict:
        return self._request("/recording/status")

    def preview_source(self) -> dict:
        return self._request("/preview/source")

    def set_preview_source(self, source: str) -> dict:
        if source not in {"digital", "analog"}:
            raise JetsonRecordingError("preview source must be digital or analog")
        return self._request("/preview/source", "POST", {"source": source})

    def start(self, label: str, video_port: int, api_port: int) -> dict:
        return self._request(
            "/recording/start",
            "POST",
            {
                "label": label,
                "video_port": video_port,
                "api_port": api_port,
            },
        )

    def stop(self) -> dict:
        return self._request("/recording/stop", "POST")
