#!/usr/bin/env python3
"""Control the Jetson high-resolution split pipeline over the private network.

The GCS backend calls this small standard-library HTTP service. The service
starts one child process for ``arducam_split_pipeline.py`` and stops it with
SIGINT so the MP4 muxer receives EOS and finalizes the local recording.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Jetson/Linux provides fcntl.
    fcntl = None

try:
    from .mission_storage import MissionCatalog, MissionStorageError
    from .model_provenance import DEFAULT_MANIFEST_PATH, ModelProvenanceError, ProductionModelManifest
    from .storage_guard import StorageGuardError, validate_record_storage
except ImportError:  # Script execution from the Jetson service directory.
    from mission_storage import MissionCatalog, MissionStorageError
    from model_provenance import DEFAULT_MANIFEST_PATH, ModelProvenanceError, ProductionModelManifest
    from storage_guard import StorageGuardError, validate_record_storage


class RecordingAgentError(RuntimeError):
    pass


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RecordingAgentError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RecordingAgentError(f"{name} must be between {minimum} and {maximum}")
    return value


def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RecordingAgentError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise RecordingAgentError(f"{name} must be between {minimum} and {maximum}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RecordingAgentError(f"{name} must be true or false")


def normalize_gcs_host(value: Any, name: str = "gcs_host") -> str:
    """Validate a destination without allowing URL/argument injection."""

    if not isinstance(value, str):
        raise RecordingAgentError(f"{name} must be a string")
    host = value.strip()
    if not host:
        raise RecordingAgentError(f"{name} must not be empty")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not re.fullmatch(
            r"(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?",
            host,
        ):
            raise RecordingAgentError(f"{name} must be a valid IPv4 address or hostname")
        return host.rstrip(".")
    if address.version != 4:
        raise RecordingAgentError(
            f"{name} must be IPv4 because the current RTP sender uses IPv4 UDP"
        )
    return str(address)


class AgentConfig:
    def __init__(self):
        self.bind_address = os.getenv("JETSON_RECORDING_AGENT_BIND_ADDRESS", "0.0.0.0")
        self.port = env_int("JETSON_RECORDING_AGENT_PORT", 5101, 1, 65535)
        self.token = os.getenv("JETSON_RECORDING_AGENT_TOKEN", "").strip()
        if not self.token:
            raise RecordingAgentError("JETSON_RECORDING_AGENT_TOKEN must be configured")
        raw_gcs_host = os.getenv("JETSON_GCS_HOST", "").strip()
        self.gcs_host = normalize_gcs_host(raw_gcs_host, "JETSON_GCS_HOST") if raw_gcs_host else None
        self.allow_gcs_host_override = env_bool("JETSON_ALLOW_GCS_HOST_OVERRIDE", False)
        self.gcs_api_port = env_int("JETSON_GCS_API_PORT", 5001, 1, 65535)

        self.pipeline_script = Path(
            os.getenv(
                "JETSON_RECORDING_PIPELINE_SCRIPT",
                str(Path(__file__).with_name("arducam_split_pipeline.py")),
            )
        ).expanduser().resolve()
        if not self.pipeline_script.is_file():
            raise RecordingAgentError(f"pipeline script was not found: {self.pipeline_script}")

        # The recording agent itself is intentionally lightweight and may run
        # with the system Python.  Detection can require a separate Jetson
        # runtime (Torch, Ultralytics, and custom model modules), so keep the
        # child interpreter explicit instead of inheriting sys.executable.
        # Keep the venv symlink spelling intact.  Resolving it to
        # /usr/bin/python3.10 would bypass the venv's site-packages.
        self.inference_python = Path(
            os.getenv("JETSON_INFERENCE_PYTHON", sys.executable)
        ).expanduser()
        if not self.inference_python.is_file():
            raise RecordingAgentError(
                f"inference Python executable was not found: {self.inference_python}"
            )
        self.inference_pythonpath = os.getenv("JETSON_INFERENCE_PYTHONPATH", "").strip()

        self.record_dir = Path(
            os.getenv("JETSON_RECORD_DIR", "recordings")
        ).expanduser().resolve()
        self.record_mountpoint = os.getenv("JETSON_RECORD_MOUNTPOINT", "").strip() or None
        min_free_gb = env_float("JETSON_RECORD_MIN_FREE_GB", 10.0, 0, 1024 * 1024)
        self.record_min_free_bytes = int(min_free_gb * 1024**3)
        self.allow_root_record_dir = env_bool("JETSON_ALLOW_ROOT_RECORD_DIR", False)
        self.storage_guard = env_bool("JETSON_STORAGE_GUARD", True)
        self.eos_timeout_seconds = env_float("JETSON_EOS_TIMEOUT_SECONDS", 30.0, 1, 300)
        self.stop_timeout_seconds = env_float("JETSON_STOP_TIMEOUT_SECONDS", 60.0, 10, 300)
        self.video_port = env_int("JETSON_VIDEO_PORT", 5000, 1, 65535)
        self.payload_type = env_int("JETSON_VIDEO_PAYLOAD_TYPE", 96, 0, 127)
        self.sensor_id = env_int("JETSON_SENSOR_ID", 0, 0, 16)
        # nvvidconv flip-method: 0 none, 2 = 180 rotation for an upside-down mount.
        self.flip_method = env_int("JETSON_FLIP_METHOD", 0, 0, 7)
        self.high_width = env_int("JETSON_HIGH_WIDTH", 1920, 16, 7680)
        self.high_height = env_int("JETSON_HIGH_HEIGHT", 1080, 16, 7680)
        self.high_fps = env_float("JETSON_HIGH_FPS", 30.0, 0.1, 120.0)
        self.network_width = env_int("JETSON_NETWORK_WIDTH", 960, 16, 7680)
        self.network_height = env_int("JETSON_NETWORK_HEIGHT", 540, 16, 7680)
        self.network_fps = env_float("JETSON_NETWORK_FPS", 15.0, 0.1, 120.0)
        self.local_bitrate_kbps = env_int("JETSON_LOCAL_BITRATE_KBPS", 12000, 100, 100000)
        self.network_bitrate_kbps = env_int("JETSON_NETWORK_BITRATE_KBPS", 2000, 100, 100000)
        self.easycap_device = os.getenv("JETSON_EASYCAP_DEVICE", "").strip()
        self.easycap_width = env_int("JETSON_EASYCAP_WIDTH", 640, 16, 7680)
        self.easycap_height = env_int("JETSON_EASYCAP_HEIGHT", 480, 16, 7680)
        self.easycap_fps = env_float("JETSON_EASYCAP_FPS", 30.0, 0.1, 120.0)
        self.sidecar_queue_size = env_int("JETSON_SIDECAR_QUEUE_SIZE", 4096, 1, 65536)
        self.weights = os.getenv("JETSON_MODEL_WEIGHTS", "").strip()
        self.device = os.getenv("JETSON_MODEL_DEVICE", "cuda:0").strip()
        self.imgsz = env_int("JETSON_MODEL_IMGSZ", 640, 16, 7680)
        self.conf = env_float("JETSON_MODEL_CONF", 0.45, 0, 1)
        self.sahi = env_bool("JETSON_MODEL_SAHI", False)
        self.sahi_standard_pred = env_bool("JETSON_MODEL_SAHI_STANDARD_PRED", False)
        self.slice_width = env_int("JETSON_MODEL_SLICE_WIDTH", 640, 16, 7680)
        self.slice_height = env_int("JETSON_MODEL_SLICE_HEIGHT", 640, 16, 7680)
        self.overlap = env_float("JETSON_MODEL_OVERLAP", 0.2, 0, 0.99)
        self.ingest_url = os.getenv("JETSON_DETECTION_OVERLAY_URL", "").strip() or None
        self.event_ingest_url = os.getenv("JETSON_DETECTION_EVENT_URL", "").strip() or None
        self.model_manifest_path = Path(
            os.getenv("JETSON_MODEL_MANIFEST", str(DEFAULT_MANIFEST_PATH))
        ).expanduser().resolve()
        self.verified_model = None
        if self.weights:
            try:
                manifest = ProductionModelManifest(self.model_manifest_path)
                manifest.validate_runtime(
                    device=self.device,
                    imgsz=self.imgsz,
                    confidence=self.conf,
                    sahi=self.sahi,
                )
                self.verified_model = manifest.verify(self.weights)
            except ModelProvenanceError as exc:
                raise RecordingAgentError(str(exc)) from exc
            self.weights = str(self.verified_model.path)
        self.ingest_token = os.getenv("JETSON_INGEST_TOKEN", "").strip()
        if not self.ingest_token:
            raise RecordingAgentError("JETSON_INGEST_TOKEN must be configured")

    def command(
        self,
        session_id: str,
        label: str | None,
        capture_epoch: int = 1,
        gcs_host: str | None = None,
        video_port: int | None = None,
        api_port: int | None = None,
    ) -> list[str]:
        target_host = gcs_host or self.gcs_host
        if not target_host:
            raise RecordingAgentError(
                "GCS host is unavailable; call /recording/start directly from the GCS "
                "or configure JETSON_GCS_HOST as a fallback"
            )
        target_video_port = video_port or self.video_port
        target_api_port = api_port or self.gcs_api_port
        ingest_url = self.ingest_url or (
            f"http://{target_host}:{target_api_port}/api/v1/detection/overlay"
        )
        event_ingest_url = self.event_ingest_url or (
            f"http://{target_host}:{target_api_port}/api/v1/detection/ingest"
        )
        registration_url = f"http://{target_host}:{target_api_port}/api/v1/stream/register"
        command = [
            str(self.inference_python),
            str(self.pipeline_script),
            "--host",
            target_host,
            "--port",
            str(target_video_port),
            "--payload-type",
            str(self.payload_type),
            "--sensor-id",
            str(self.sensor_id),
            "--flip-method",
            str(self.flip_method),
            "--high-width",
            str(self.high_width),
            "--high-height",
            str(self.high_height),
            "--high-fps",
            str(self.high_fps),
            "--network-width",
            str(self.network_width),
            "--network-height",
            str(self.network_height),
            "--network-fps",
            str(self.network_fps),
            "--local-bitrate-kbps",
            str(self.local_bitrate_kbps),
            "--network-bitrate-kbps",
            str(self.network_bitrate_kbps),
            "--record-dir",
            str(self.record_dir),
            "--min-free-bytes",
            str(self.record_min_free_bytes),
            "--eos-timeout-seconds",
            str(self.eos_timeout_seconds),
            "--mission-id",
            session_id,
            "--capture-epoch",
            str(capture_epoch),
            "--sidecar-queue-size",
            str(self.sidecar_queue_size),
            "--device",
            self.device,
            "--imgsz",
            str(self.imgsz),
            "--conf",
            str(self.conf),
            "--slice-width",
            str(self.slice_width),
            "--slice-height",
            str(self.slice_height),
            "--overlap",
            str(self.overlap),
            "--ingest-url",
            ingest_url,
            "--event-ingest-url",
            event_ingest_url,
            "--ingest-token",
            self.ingest_token,
            "--registration-url",
            registration_url,
        ]
        if self.easycap_device and Path(self.easycap_device).exists():
            command.extend([
                "--easycap-device", self.easycap_device,
                "--easycap-width", str(self.easycap_width),
                "--easycap-height", str(self.easycap_height),
                "--easycap-fps", str(self.easycap_fps),
                "--preview-source-file", str(self.record_dir / ".preview-source"),
            ])
        if self.record_mountpoint:
            command.extend(["--mountpoint", self.record_mountpoint])
        if self.allow_root_record_dir:
            command.append("--allow-root-record-dir")
        if label:
            command.extend(["--label", label])
        if self.weights:
            command.extend([
                "--weights", self.weights,
                "--model-manifest", str(self.model_manifest_path),
            ])
        if self.sahi:
            command.append("--sahi")
        if self.sahi_standard_pred:
            command.append("--sahi-standard-pred")
        return command

    def pipeline_environment(self) -> dict[str, str]:
        """Return child environment without changing the agent process."""

        environment = os.environ.copy()
        if self.inference_pythonpath:
            existing = environment.get("PYTHONPATH", "")
            environment["PYTHONPATH"] = (
                f"{self.inference_pythonpath}{os.pathsep}{existing}"
                if existing
                else self.inference_pythonpath
            )
        return environment


class RecordingController:
    def __init__(self, config: AgentConfig):
        self.config = config
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._pid: int | None = None
        self._session_id: str | None = None
        self._capture_epoch: int | None = None
        self._session_dir: Path | None = None
        self._label: str | None = None
        self._gcs_host: str | None = None
        self._video_port: int | None = None
        self._api_port: int | None = None
        self._started_at: float | None = None
        self._ended_at: float | None = None
        self._stop_requested = False
        self._last: dict[str, Any] | None = None
        self._lock_file = None
        self._active_state_path = self.config.record_dir / ".recording-agent.active.json"
        self._lock_path = self.config.record_dir / ".recording-agent.lock"
        self._storage_guard_enabled = bool(getattr(config, "storage_guard", False))
        self._mission_catalog = MissionCatalog(self.config.record_dir)
        self._catalog_finalized = False
        if self._storage_guard_enabled:
            try:
                validate_record_storage(
                    self.config.record_dir,
                    # Service startup must remain able to report/stop a
                    # recovered session even if a previous recording already
                    # consumed the configured reserve. The reserve is
                    # enforced when a new session starts below.
                    min_free_bytes=0,
                    mountpoint=self.config.record_mountpoint,
                    allow_root=self.config.allow_root_record_dir,
                )
            except StorageGuardError as exc:
                raise RecordingAgentError(str(exc)) from exc
        self._acquire_lock()
        self._recover_active_state()

    def _acquire_lock(self) -> None:
        """Fence competing recording-agent processes on the same Jetson."""

        if fcntl is None:
            return
        try:
            self.config.record_dir.mkdir(parents=True, exist_ok=True)
            self._lock_file = self._lock_path.open("a+", encoding="utf-8")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            if self._lock_file is not None:
                self._lock_file.close()
                self._lock_file = None
            raise RecordingAgentError(
                f"another recording agent owns {self.config.record_dir}: {exc}"
            ) from exc

    def _release_lock(self) -> None:
        if self._lock_file is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock_file.close()
            self._lock_file = None

    @staticmethod
    def _pid_is_alive(pid: int | None) -> bool:
        if not pid or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def _pid_is_pipeline(self, pid: int | None) -> bool:
        if not self._pid_is_alive(pid):
            return False
        if os.name == "nt":
            return True
        try:
            command_line = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(
                "utf-8", errors="replace"
            )
        except OSError:
            return False
        return str(self.config.pipeline_script) in command_line or self.config.pipeline_script.name in command_line

    def _write_active_state(self) -> None:
        payload = {
            "pid": self._pid,
            "session_id": self._session_id,
            "capture_epoch": self._capture_epoch,
            "session_dir": str(self._session_dir) if self._session_dir else None,
            "label": self._label,
            "gcs_host": self._gcs_host,
            "video_port": self._video_port,
            "api_port": self._api_port,
            "started_at": self._started_at,
            "pipeline_script": str(self.config.pipeline_script),
        }
        temporary = self._active_state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(self._active_state_path)

    def _clear_active_state(self) -> None:
        try:
            self._active_state_path.unlink()
        except FileNotFoundError:
            pass

    def _recover_active_state(self) -> None:
        """Recover status/control of a child if the agent itself restarted."""

        try:
            payload = json.loads(self._active_state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            self._clear_active_state()
            return
        try:
            pid = int(payload.get("pid"))
        except (TypeError, ValueError):
            self._clear_active_state()
            return
        if not self._pid_is_pipeline(pid):
            self._clear_active_state()
            return
        session_dir = payload.get("session_dir")
        if not session_dir:
            self._clear_active_state()
            return
        self._pid = pid
        self._session_id = payload.get("session_id")
        self._capture_epoch = int(payload.get("capture_epoch") or 1)
        self._session_dir = Path(session_dir)
        self._label = payload.get("label")
        self._gcs_host = payload.get("gcs_host") or getattr(self.config, "gcs_host", None)
        self._video_port = payload.get("video_port") or getattr(self.config, "video_port", 5000)
        self._api_port = payload.get("api_port") or getattr(self.config, "gcs_api_port", 5001)
        self._started_at = payload.get("started_at")
        self._ended_at = None
        self._stop_requested = False

    def _process_alive_locked(self) -> bool:
        if self._process is not None:
            return self._process.poll() is None
        return self._pid_is_pipeline(self._pid)

    def _metadata(self) -> dict[str, Any]:
        if not self._session_dir:
            return {}
        if self._capture_epoch is None:
            return {}
        path = self._session_dir / "epochs" / f"{self._capture_epoch:04d}" / "epoch.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _state_locked(self) -> dict[str, Any]:
        process = self._process
        if self._process_alive_locked():
            metadata = self._metadata()
            status = "STOPPING" if self._stop_requested else metadata.get("status", "STARTING")
            status = status if status in {"STARTING", "RECORDING", "STOPPING"} else "RECORDING"
            return self._response_locked(status, True, metadata=metadata)

        if process is not None or self._pid is not None:
            returncode = process.poll() if process is not None else None
            self._ended_at = self._ended_at or time.time()
            metadata = self._metadata()
            status = metadata.get("status")
            if status not in {"COMPLETED", "FAILED"}:
                status = "COMPLETED" if returncode == 0 else "FAILED"
            error = metadata.get("error") or (
                None if returncode == 0 else f"pipeline exited with code {returncode}"
            )
            self._last = self._response_locked(status, False, metadata=metadata, error=error)
            if self._session_id and self._capture_epoch and not self._catalog_finalized:
                try:
                    self._mission_catalog.finalize_epoch(
                        self._session_id, self._capture_epoch, status, error
                    )
                except MissionStorageError as exc:
                    self._last["error"] = self._last.get("error") or str(exc)
                self._catalog_finalized = True
            self._process = None
            self._pid = None
            self._clear_active_state()
            return self._last

        if self._last is not None:
            return dict(self._last)
        return self._response_locked("IDLE", False)

    def _response_locked(
        self,
        status: str,
        recording: bool,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        metadata = metadata or {}
        started_at = self._started_at
        ended_at = self._ended_at
        duration = 0
        if started_at:
            duration = max(0, (time.time() if recording else ended_at or time.time()) - started_at)
        return {
            "ok": True,
            "recording": recording,
            "state_known": True,
            "status": status,
            "session_id": self._session_id,
            "mission_id": self._session_id,
            "capture_epoch": self._capture_epoch,
            "session_dir": str(self._session_dir) if self._session_dir else None,
            "started_at": started_at,
            "ended_at": ended_at,
            "frame_count": metadata.get("frame_count", 0),
            "duration_seconds": duration,
            "label": self._label,
            "error": error if error is not None else metadata.get("error"),
            "pid": self._process.pid if self._process is not None else self._pid,
            "highres": metadata.get("highres"),
            "network": metadata.get("network"),
            "storage": metadata.get("storage"),
            "detector": metadata.get("detector"),
            "health": metadata.get("health"),
            "preview_source": self._read_preview_source() if self._analog_available() else "digital",
            "preview_analog_available": self._analog_available(),
            "preview_active_source": (
                metadata.get("preview", {}).get("source")
                if metadata
                else self._read_preview_source() if self._analog_available() else "digital"
            ),
            "stream_target": {
                "host": self._gcs_host,
                "video_port": self._video_port,
                "api_port": self._api_port,
            } if self._gcs_host else None,
        }

    def _preview_source_path(self) -> Path:
        return Path(self.config.record_dir).expanduser().resolve() / ".preview-source"

    def _read_preview_source(self) -> str:
        try:
            value = self._preview_source_path().read_text(encoding="utf-8").strip().lower()
        except OSError:
            return "digital"
        return value if value in {"digital", "analog"} else "digital"

    def _write_preview_source(self, source: str) -> None:
        path = self._preview_source_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source + "\n", encoding="utf-8")

    def _analog_available(self) -> bool:
        device = getattr(self.config, "easycap_device", "")
        return bool(device and Path(device).exists())

    def set_preview_source(self, source: Any) -> dict[str, Any]:
        if not isinstance(source, str):
            raise RecordingAgentError("preview source must be digital or analog")
        normalized = source.strip().lower()
        if normalized not in {"digital", "analog"}:
            raise RecordingAgentError("preview source must be digital or analog")
        if normalized == "analog" and not self._analog_available():
            raise RecordingAgentError(
                "analog preview is unavailable; configure JETSON_EASYCAP_DEVICE and connect EasyCAP"
            )
        with self._lock:
            self._write_preview_source(normalized)
            return self._state_locked()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._state_locked()

    @staticmethod
    def _runtime_port(value: Any, fallback: int, name: str) -> int:
        if value is None:
            return fallback
        if isinstance(value, bool):
            raise RecordingAgentError(f"{name} must be an integer")
        try:
            port = int(value)
        except (TypeError, ValueError) as exc:
            raise RecordingAgentError(f"{name} must be an integer") from exc
        if not 1 <= port <= 65535:
            raise RecordingAgentError(f"{name} must be between 1 and 65535")
        return port

    def _runtime_gcs_host(self, requested_host: Any, request_host: str | None) -> str:
        caller = normalize_gcs_host(request_host, "request source IP") if request_host else None
        if requested_host is not None:
            requested = normalize_gcs_host(requested_host)
            allow_override = bool(getattr(self.config, "allow_gcs_host_override", False))
            if caller and requested != caller and not allow_override:
                raise RecordingAgentError(
                    "gcs_host override does not match the request source; set "
                    "JETSON_ALLOW_GCS_HOST_OVERRIDE=true only when routing requires an override"
                )
            return requested
        fallback = getattr(self.config, "gcs_host", None)
        if caller:
            return caller
        if fallback:
            return normalize_gcs_host(fallback, "JETSON_GCS_HOST")
        raise RecordingAgentError(
            "GCS host could not be detected and JETSON_GCS_HOST is not configured"
        )

    def start(
        self,
        label: str | None = None,
        *,
        request_host: str | None = None,
        gcs_host: Any = None,
        video_port: Any = None,
        api_port: Any = None,
        mission_id: Any = None,
    ) -> dict[str, Any]:
        with self._lock:
            current = self._state_locked()
            if current["recording"]:
                return current

            target_host = self._runtime_gcs_host(gcs_host, request_host)
            target_video_port = self._runtime_port(
                video_port, getattr(self.config, "video_port", 5000), "video_port"
            )
            target_api_port = self._runtime_port(
                api_port, getattr(self.config, "gcs_api_port", 5001), "api_port"
            )

            if self._storage_guard_enabled:
                try:
                    validate_record_storage(
                        self.config.record_dir,
                        min_free_bytes=self.config.record_min_free_bytes,
                        mountpoint=self.config.record_mountpoint,
                        allow_root=self.config.allow_root_record_dir,
                    )
                except StorageGuardError as exc:
                    raise RecordingAgentError(str(exc)) from exc
            else:
                self.config.record_dir.mkdir(parents=True, exist_ok=True)
            try:
                session_id, capture_epoch, mission_dir = self._mission_catalog.allocate(
                    mission_id, label
                )
            except MissionStorageError as exc:
                raise RecordingAgentError(str(exc)) from exc
            self._session_id = session_id
            self._capture_epoch = capture_epoch
            self._session_dir = mission_dir
            self._label = (label or "").strip() or None
            self._gcs_host = target_host
            self._video_port = target_video_port
            self._api_port = target_api_port
            self._started_at = time.time()
            self._ended_at = None
            self._stop_requested = False
            self._catalog_finalized = False
            self._write_preview_source("digital")
            command = self.config.command(
                session_id,
                self._label,
                capture_epoch=capture_epoch,
                gcs_host=target_host,
                video_port=target_video_port,
                api_port=target_api_port,
            )
            try:
                # Fence the always-on preview before creating the child. The
                # preview service polls this marker before opening the same
                # camera devices; writing it after Popen introduces a race
                # where both GStreamer pipelines try to claim the camera.
                self._write_active_state()
                self._process = subprocess.Popen(
                    command,
                    cwd=str(self.config.pipeline_script.parent.parent),
                    env=self.config.pipeline_environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=None,
                    stderr=None,
                    start_new_session=True,
                )
                self._pid = self._process.pid
                self._write_active_state()
            except OSError as exc:
                self._process = None
                self._pid = None
                self._ended_at = time.time()
                self._clear_active_state()
                self._last = self._response_locked("FAILED", False, error=str(exc))
                self._mission_catalog.finalize_epoch(
                    session_id, capture_epoch, "FAILED", str(exc)
                )
                self._catalog_finalized = True
                raise RecordingAgentError(f"cannot start Jetson pipeline: {exc}") from exc
            except Exception:
                process = self._process
                self._process = None
                self._pid = None
                self._clear_active_state()
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                raise
            return self._state_locked()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            current = self._state_locked()
            process = self._process
            pid = self._pid
            if (process is None and pid is None) or not current["recording"]:
                return current
            self._stop_requested = True

        try:
            if process is not None:
                process.send_signal(signal.SIGINT)
                process.wait(timeout=getattr(self.config, "stop_timeout_seconds", 60.0))
            elif pid is not None:
                self._signal_and_wait(
                    pid,
                    signal.SIGINT,
                    getattr(self.config, "stop_timeout_seconds", 60.0),
                )
        except subprocess.TimeoutExpired:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            elif pid is not None and self._pid_is_alive(pid):
                self._signal_and_wait(pid, signal.SIGTERM, 10)
                if self._pid_is_alive(pid):
                    self._signal_and_wait(pid, signal.SIGKILL, 10)
            self._launch_postflight_snapshots()
            with self._lock:
                self._ended_at = self._ended_at or time.time()
                return self._state_locked()

    def _launch_postflight_snapshots(self) -> None:
        """Fire-and-forget: generate the hover-preview snapshots + manifest
        for the epoch that just finished, in the background. Never block or
        fail the stop() response on this -- it's a convenience feature, not
        part of the recording contract. See
        docs/post-flight-detection-snapshots.md."""

        if not self._session_dir or not self._capture_epoch:
            return
        epoch_dir = self._session_dir / "epochs" / f"{self._capture_epoch:04d}"
        script = self.config.pipeline_script.with_name("generate_detection_snapshots.py")
        if not script.is_file():
            return
        try:
            subprocess.Popen(
                [sys.executable, str(script), str(epoch_dir)],
                cwd=str(script.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            print(f"[recording-agent] could not launch post-flight snapshot generation: {exc}", flush=True)

    def _signal_and_wait(self, pid: int, sig: signal.Signals, timeout: float) -> None:
        try:
            os.kill(pid, sig)
        except (OSError, ProcessLookupError):
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._pid_is_pipeline(pid):
                return
            time.sleep(0.25)

    def shutdown(self) -> None:
        with self._lock:
            active = self._process_alive_locked()
        if active:
            self.stop()
        self._release_lock()


class RecordingRequestHandler(BaseHTTPRequestHandler):
    controller: RecordingController

    def _authorized(self) -> bool:
        expected = self.controller.config.token
        if not expected:
            return True
        received = self.headers.get("Authorization", "")
        return hmac.compare_digest(received, f"Bearer {expected}")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 64 * 1024:
            raise RecordingAgentError("request body is too large")
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordingAgentError("request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise RecordingAgentError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "Unauthorized"})
            return
        if self.path == "/preview/source":
            self._send_json(200, {
                "ok": True,
                "preview_source": self.controller._read_preview_source() if self.controller._analog_available() else "digital",
                "preview_analog_available": self.controller._analog_available(),
            })
            return
        if self.path != "/recording/status":
            self._send_json(404, {"ok": False, "error": "Not found"})
            return
        self._send_json(200, self.controller.status())

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "Unauthorized"})
            return
        try:
            payload = self._read_json()
            if self.path == "/preview/source":
                result = self.controller.set_preview_source(payload.get("source"))
                self._send_json(200, result)
                return
            if self.path == "/recording/start":
                label = payload.get("label")
                if label is not None and not isinstance(label, str):
                    raise RecordingAgentError("label must be a string")
                result = self.controller.start(
                    label,
                    request_host=self.client_address[0],
                    gcs_host=payload.get("gcs_host"),
                    video_port=payload.get("video_port"),
                    api_port=payload.get("api_port"),
                    mission_id=payload.get("mission_id"),
                )
                self._send_json(202, result)
                return
            if self.path == "/recording/stop":
                self._send_json(200, self.controller.stop())
                return
            self._send_json(404, {"ok": False, "error": "Not found"})
        except RecordingAgentError as exc:
            self._send_json(409, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[recording-agent] {self.address_string()} - {format % args}", flush=True)


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines from a local .env for manual runs.

    Real environment variables always win, so the systemd EnvironmentFile stays
    authoritative for the service.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


def main() -> int:
    load_env_file(Path(__file__).with_name(".env"))
    config = AgentConfig()
    controller = RecordingController(config)
    RecordingRequestHandler.controller = controller
    server = ThreadingHTTPServer((config.bind_address, config.port), RecordingRequestHandler)
    server.daemon_threads = True

    def stop_server(*_args):
        controller.shutdown()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)
    print(
        f"[recording-agent] listening on {config.bind_address}:{config.port}; "
        f"GCS=auto-detect (fallback={config.gcs_host or 'none'}); "
        f"default-video-port={config.video_port}",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        controller.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecordingAgentError as exc:
        print(f"[recording-agent] fatal: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
