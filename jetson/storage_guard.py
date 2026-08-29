#!/usr/bin/env python3
"""Safety checks for Jetson flight-recording storage.

The recorder must never silently fall back to the Jetson root filesystem when
the removable SSD is not mounted.  This module deliberately uses only local
filesystem operations so it can run before a recording process is spawned.
"""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_MIN_FREE_BYTES = 10 * 1024**3


class StorageGuardError(RuntimeError):
    """Raised when the configured recording storage is unsafe."""


@dataclass(frozen=True)
class StorageInfo:
    record_dir: Path
    mountpoint: Path
    device_id: int
    total_bytes: int
    used_bytes: int
    free_bytes: int
    min_free_bytes: int

    def as_dict(self) -> dict[str, int | str]:
        values = asdict(self)
        values["record_dir"] = str(self.record_dir)
        values["mountpoint"] = str(self.mountpoint)
        return values


def _real_path(value: str | Path) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(value))))


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def find_mountpoint(path: str | Path) -> Path:
    """Return the nearest mount containing ``path``."""

    candidate = _existing_ancestor(_real_path(path))
    while True:
        if candidate.is_mount():
            return candidate
        if candidate == candidate.parent:
            return candidate
        candidate = candidate.parent


def _is_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(parent))) == str(parent)
    except ValueError:
        return False


def validate_record_storage(
    record_dir: str | Path,
    *,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    mountpoint: str | Path | None = None,
    allow_root: bool = False,
    write_probe: bool = True,
) -> StorageInfo:
    """Validate and prepare the recording directory.

    ``allow_root`` exists only for controlled development/test setups. The
    production agent leaves it disabled, so an unmounted SSD is rejected
    instead of being hidden by the root mount.
    """

    if min_free_bytes < 0:
        raise StorageGuardError("minimum free storage cannot be negative")

    requested = _real_path(record_dir)
    detected_mount = _real_path(mountpoint) if mountpoint else find_mountpoint(requested)
    if not detected_mount.is_mount():
        raise StorageGuardError(f"recording mountpoint is not mounted: {detected_mount}")
    if detected_mount == Path("/") and not allow_root:
        raise StorageGuardError(
            f"recording storage is on the root filesystem; SSD mount is unavailable for {requested}"
        )
    if not _is_within(requested, detected_mount):
        raise StorageGuardError(
            f"recording directory {requested} is outside mountpoint {detected_mount}"
        )

    existing = _existing_ancestor(requested)
    try:
        mount_device = os.stat(detected_mount).st_dev
        existing_device = os.stat(existing).st_dev
    except OSError as exc:
        raise StorageGuardError(f"cannot inspect recording storage: {exc}") from exc
    if mount_device != existing_device:
        raise StorageGuardError(
            f"recording directory is not on the configured mount: {requested}"
        )

    try:
        requested.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageGuardError(f"cannot create recording directory {requested}: {exc}") from exc
    if not requested.is_dir() or not os.access(requested, os.W_OK):
        raise StorageGuardError(f"recording directory is not writable: {requested}")

    try:
        usage = shutil.disk_usage(requested)
    except OSError as exc:
        raise StorageGuardError(f"cannot inspect free space for {requested}: {exc}") from exc
    if usage.free < min_free_bytes:
        raise StorageGuardError(
            f"not enough free space on {detected_mount}: "
            f"{usage.free} bytes available, {min_free_bytes} required"
        )

    if write_probe:
        probe = requested / f".recording-write-test-{os.getpid()}-{uuid.uuid4().hex}"
        try:
            with probe.open("xb") as handle:
                handle.write(b"recording-storage-ok\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise StorageGuardError(f"recording storage is not writable: {exc}") from exc
        finally:
            try:
                probe.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise StorageGuardError(f"cannot remove storage probe {probe}: {exc}") from exc

    return StorageInfo(
        record_dir=requested,
        mountpoint=detected_mount,
        device_id=mount_device,
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        min_free_bytes=min_free_bytes,
    )
