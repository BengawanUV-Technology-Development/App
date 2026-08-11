"""Role-scoped bearer authentication for operator and Jetson traffic."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from flask import Request, jsonify


@dataclass(frozen=True, slots=True)
class TokenConfig:
    operator: str
    ingest: str
    recording_agent: str

    @classmethod
    def from_env(cls) -> "TokenConfig":
        return cls(
            operator=os.getenv("BUV_OPERATOR_TOKEN", "").strip(),
            ingest=os.getenv("JETSON_INGEST_TOKEN", "").strip(),
            recording_agent=os.getenv("JETSON_RECORDING_AGENT_TOKEN", "").strip(),
        )


class BearerAuthenticator:
    """Classify API traffic and reject missing/wrong role tokens.

    Read-only telemetry and health endpoints remain public. All mutations use
    the operator token except Jetson ingest endpoints, which use the dedicated
    ingest token. WebSockets accept the operator token through the query string
    because the browser WebSocket constructor cannot set Authorization.
    """

    INGEST_PATHS = frozenset(
        {
            "/api/v1/detection/overlay",
            "/api/v1/detection/ingest",
            "/api/v1/stream/register",
            "/api/v1/ingest/health",
        }
    )
    OPERATOR_SOCKET_PATHS = frozenset({"/api/v1/events", "/api/v1/vision/ws"})

    def __init__(self, config: TokenConfig):
        self.config = config

    def required_role(self, request: Request) -> str | None:
        if request.path in self.OPERATOR_SOCKET_PATHS:
            return "operator"
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        if request.path in self.INGEST_PATHS:
            return "ingest"
        if request.path.startswith("/api/v1/"):
            return "operator"
        return None

    @staticmethod
    def _bearer(request: Request) -> str:
        header = request.headers.get("Authorization", "")
        prefix, separator, value = header.partition(" ")
        if separator and prefix.lower() == "bearer":
            return value.strip()
        return ""

    def authenticate(self, request: Request):
        role = self.required_role(request)
        if role is None:
            return None
        expected = self.config.operator if role == "operator" else self.config.ingest
        supplied = request.args.get("token", "") if request.path in self.OPERATOR_SOCKET_PATHS else self._bearer(request)
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            response = jsonify({"ok": False, "error": "unauthorized", "required_role": role})
            response.status_code = 401
            response.headers["WWW-Authenticate"] = 'Bearer realm="buv"'
            return response
        return None
