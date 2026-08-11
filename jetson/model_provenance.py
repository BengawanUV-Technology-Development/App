"""Production model manifest and immutable checkpoint verification."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST_PATH = Path(__file__).with_name("production_model.json")


class ModelProvenanceError(RuntimeError):
    """Raised when a detector artifact does not match the frozen manifest."""


@dataclass(frozen=True, slots=True)
class VerifiedModel:
    model_id: str
    architecture: str
    variant: str
    path: Path
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "architecture": self.architecture,
            "variant": self.variant,
            "path": str(self.path),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "provenance": "VERIFIED",
        }


class ProductionModelManifest:
    def __init__(self, path: str | Path = DEFAULT_MANIFEST_PATH):
        self.path = Path(path).expanduser().resolve()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelProvenanceError(f"cannot read production model manifest: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != "1":
            raise ModelProvenanceError("production model manifest must use schema_version 1")

        checkpoint = payload.get("checkpoint")
        runtime = payload.get("runtime")
        if not isinstance(checkpoint, dict) or not isinstance(runtime, dict):
            raise ModelProvenanceError("production model manifest is missing checkpoint/runtime")
        expected_sha256 = str(checkpoint.get("sha256", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ModelProvenanceError("production checkpoint sha256 is invalid")
        expected_size = checkpoint.get("size_bytes")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size <= 0:
            raise ModelProvenanceError("production checkpoint size_bytes is invalid")

        self.payload = payload
        self.model_id = str(payload.get("model_id", "")).strip()
        self.architecture = str(payload.get("architecture", "")).strip()
        self.variant = str(payload.get("variant", "")).strip()
        if not self.model_id or not self.architecture or not self.variant:
            raise ModelProvenanceError("production model identity fields must not be empty")
        self.expected_sha256 = expected_sha256
        self.expected_size = expected_size

    def validate_runtime(self, *, device: str, imgsz: int, confidence: float, sahi: bool) -> None:
        expected = self.payload["runtime"]
        if device != expected.get("device"):
            raise ModelProvenanceError(f"production detector device must be {expected.get('device')}")
        if imgsz != expected.get("imgsz"):
            raise ModelProvenanceError(f"production detector imgsz must be {expected.get('imgsz')}")
        if not math.isclose(float(confidence), float(expected.get("confidence")), abs_tol=1e-9):
            raise ModelProvenanceError(
                f"production detector confidence must be {expected.get('confidence')}"
            )
        if bool(sahi) != bool(expected.get("sahi")):
            raise ModelProvenanceError("SAHI must remain disabled for the first production profile")

    def verify(self, path: str | Path) -> VerifiedModel:
        checkpoint_path = Path(path).expanduser().resolve()
        try:
            size = checkpoint_path.stat().st_size
        except OSError as exc:
            raise ModelProvenanceError(f"production checkpoint is unavailable: {exc}") from exc
        if not checkpoint_path.is_file():
            raise ModelProvenanceError(f"production checkpoint is not a file: {checkpoint_path}")
        if size != self.expected_size:
            raise ModelProvenanceError(
                f"production checkpoint size mismatch: expected {self.expected_size}, got {size}"
            )

        digest = hashlib.sha256()
        try:
            with checkpoint_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise ModelProvenanceError(f"cannot hash production checkpoint: {exc}") from exc
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != self.expected_sha256:
            raise ModelProvenanceError(
                "production checkpoint checksum mismatch: "
                f"expected {self.expected_sha256}, got {actual_sha256}"
            )
        return VerifiedModel(
            model_id=self.model_id,
            architecture=self.architecture,
            variant=self.variant,
            path=checkpoint_path,
            sha256=actual_sha256,
            size_bytes=size,
        )

