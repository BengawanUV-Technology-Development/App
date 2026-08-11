"""Durable mission/epoch allocation for the Jetson Recording Agent."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


class MissionStorageError(RuntimeError):
    pass


def new_mission_id() -> str:
    return f"mission-{uuid.uuid4()}"


def validate_mission_id(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("mission-"):
        raise MissionStorageError("mission_id must be mission-<uuid>")
    try:
        uuid.UUID(value.removeprefix("mission-"))
    except (ValueError, AttributeError) as exc:
        raise MissionStorageError("mission_id must be mission-<uuid>") from exc
    return value


class MissionCatalog:
    """Atomic JSON catalog kept on the same validated SSD as mission evidence."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(path)

    def read(self, mission_id: str) -> dict[str, Any]:
        validate_mission_id(mission_id)
        path = self.root / mission_id / "mission.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise MissionStorageError(f"mission does not exist: {mission_id}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise MissionStorageError(f"mission manifest is unreadable: {mission_id}: {exc}") from exc
        if payload.get("schema_version") != "2.0" or payload.get("mission_id") != mission_id:
            raise MissionStorageError(f"mission manifest has invalid v2 identity: {mission_id}")
        return payload

    def allocate(self, requested_mission_id: str | None = None, label: str | None = None) -> tuple[str, int, Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        mission_id = validate_mission_id(requested_mission_id) if requested_mission_id else new_mission_id()
        mission_dir = self.root / mission_id
        manifest_path = mission_dir / "mission.json"
        if manifest_path.exists():
            manifest = self.read(mission_id)
            recent_failures = [
                int(item) for item in manifest.get("capture_failures_ns", [])
                if time.time_ns() - int(item) <= 60_000_000_000
            ]
            if manifest.get("status") == "FAILED" or len(recent_failures) >= 3:
                raise MissionStorageError("mission is FAILED after repeated capture failures")
        else:
            mission_dir.mkdir(parents=True, exist_ok=False)
            (mission_dir / "epochs").mkdir()
            now = time.time_ns()
            manifest = {
                "schema_version": "2.0",
                "mission_id": mission_id,
                "camera_id": "arducam",
                "status": "CREATED",
                "label": (label or "").strip() or None,
                "current_epoch": 0,
                "created_utc_ns": now,
                "updated_utc_ns": now,
                "capture_failures_ns": [],
                "epochs": [],
            }
        capture_epoch = int(manifest.get("current_epoch", 0)) + 1
        epoch_relative = f"epochs/{capture_epoch:04d}"
        epoch_dir = mission_dir / epoch_relative
        if epoch_dir.exists():
            raise MissionStorageError(f"epoch collision: {mission_id}/{capture_epoch:04d}")
        manifest.update(status="RECORDING", current_epoch=capture_epoch, updated_utc_ns=time.time_ns())
        manifest.setdefault("epochs", []).append(
            {"capture_epoch": capture_epoch, "path": epoch_relative, "status": "STARTING"}
        )
        self._atomic_write(manifest_path, manifest)
        return mission_id, capture_epoch, mission_dir

    def finalize_epoch(self, mission_id: str, capture_epoch: int, status: str, error: str | None = None) -> dict[str, Any]:
        manifest = self.read(mission_id)
        now = time.time_ns()
        for epoch in manifest.get("epochs", []):
            if epoch.get("capture_epoch") == capture_epoch:
                epoch.update(status=status, ended_utc_ns=now, error=error)
                break
        if status == "FAILED":
            failures = [
                int(item) for item in manifest.get("capture_failures_ns", [])
                if now - int(item) <= 60_000_000_000
            ]
            failures.append(now)
            manifest["capture_failures_ns"] = failures
            manifest["status"] = "FAILED" if len(failures) >= 3 else "CREATED"
        else:
            manifest["status"] = "COMPLETED"
        manifest["updated_utc_ns"] = now
        self._atomic_write(self.root / mission_id / "mission.json", manifest)
        return manifest
