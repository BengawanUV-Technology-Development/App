#!/usr/bin/env python3
"""Split one Arducam capture into high-resolution CV/recording and low-res RTP.

The script is intended to run natively on a Jetson Orin Nano, where Argus and
the NVIDIA GStreamer plugins are available. It keeps one camera capture alive
and branches it before encoding:

    high-res Argus capture
        ├── high-res H.264 software encode -> local video.mp4
        ├── high-res BGR appsink -> optional YOLO/SAHI -> detections.jsonl/HTTP
        └── resize -> low-res H.264 software encode -> RTP/UDP -> GCS

The capture-only mode (no ``--weights``) still writes one explicit empty
detection record per frame and one telemetry snapshot per frame. This makes
the footage immediately usable for offline YOLO
without pretending that a detector or telemetry source was active.

Orin Nano does not provide NVENC, so x264enc is used deliberately. Start with
1920x1080 for the high-resolution branch and benchmark CPU/FPS before trying a
higher source mode.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import signal
import shutil
import socket
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

try:
    from .mavlink_telemetry import MAVLinkTelemetryCollector
    from .model_provenance import DEFAULT_MANIFEST_PATH, ProductionModelManifest, VerifiedModel
    from .rtp_identity import RtpIdentityError, inject_frame_id
    from .storage_guard import StorageInfo, validate_record_storage
except ImportError:  # Script execution from the Jetson service directory.
    from mavlink_telemetry import MAVLinkTelemetryCollector
    from model_provenance import DEFAULT_MANIFEST_PATH, ProductionModelManifest, VerifiedModel
    from rtp_identity import RtpIdentityError, inject_frame_id
    from storage_guard import StorageInfo, validate_record_storage


def utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def read_system_health() -> dict[str, Any]:
    """Best-effort Linux/Jetson resource snapshot without extra dependencies."""

    health: dict[str, Any] = {
        "cpu_load_1m": None,
        "ram_used_bytes": None,
        "ram_total_bytes": None,
        "temperature_c": None,
        "gpu": {"status": "not_available"},
    }
    try:
        health["cpu_load_1m"] = os.getloadavg()[0]
    except (AttributeError, OSError):
        pass
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
        health["ram_total_bytes"] = values.get("MemTotal")
        if values.get("MemTotal") is not None and values.get("MemAvailable") is not None:
            health["ram_used_bytes"] = values["MemTotal"] - values["MemAvailable"]
    except (OSError, ValueError, IndexError):
        pass
    temperatures = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(path.read_text(encoding="utf-8").strip())
            temperatures.append(value / 1000 if value > 1000 else value)
        except (OSError, TypeError, ValueError):
            continue
    if temperatures:
        health["temperature_c"] = max(temperatures)
    return health


def validate_dimension(value: int, name: str) -> int:
    if value < 16 or value > 7680:
        raise ValueError(f"{name} must be between 16 and 7680")
    return value


def validate_fps(value: float, name: str) -> float:
    if value <= 0 or value > 120:
        raise ValueError(f"{name} must be greater than 0 and at most 120")
    return value


def validate_bitrate(value: int, name: str) -> int:
    if value < 100 or value > 100_000:
        raise ValueError(f"{name} must be between 100 and 100000 kbps")
    return value


def fps_caps(value: float) -> str:
    """Render a Python float as a GStreamer fraction."""

    fraction = Fraction(value).limit_denominator(1000)
    return f"{fraction.numerator}/{fraction.denominator}"


def scale_bbox(bbox: list[float], source_width: int, source_height: int, target_width: int, target_height: int) -> list[int]:
    """Map an xyxy bbox between same-aspect-ratio image coordinates."""

    if len(bbox) != 4:
        raise ValueError("bbox must contain four coordinates")
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise ValueError("image dimensions must be positive")
    sx = target_width / source_width
    sy = target_height / source_height
    x1, y1, x2, y2 = bbox
    return [
        max(0, min(target_width, round(x1 * sx))),
        max(0, min(target_height, round(y1 * sy))),
        max(0, min(target_width, round(x2 * sx))),
        max(0, min(target_height, round(y2 * sy))),
    ]


def _gst_quote(value: str | Path) -> str:
    """Quote a value for Gst.parse_launch, not for a shell."""

    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def build_pipeline_description(
    args: argparse.Namespace,
    video_path: Path,
    recovery_file: Path | None = None,
) -> str:
    """Build the validated GStreamer split pipeline description."""

    high_width = validate_dimension(args.high_width, "high-width")
    high_height = validate_dimension(args.high_height, "high-height")
    network_width = validate_dimension(args.network_width, "network-width")
    network_height = validate_dimension(args.network_height, "network-height")
    high_fps = validate_fps(args.high_fps, "high-fps")
    network_fps = validate_fps(args.network_fps, "network-fps")
    host = args.host.strip()
    if network_fps > high_fps:
        raise ValueError("network-fps cannot be higher than high-fps")
    if args.sensor_id < 0:
        raise ValueError("sensor-id must be zero or greater")
    if args.port < 1 or args.port > 65535:
        raise ValueError("port must be between 1 and 65535")
    if args.payload_type < 0 or args.payload_type > 127:
        raise ValueError("payload-type must be between 0 and 127")
    if not 0 <= args.rtp_ssrc <= 0xFFFFFFFF:
        raise ValueError("rtp-ssrc must be an unsigned 32-bit integer")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", host):
        raise ValueError("host must be a single hostname or IP address")
    validate_bitrate(args.local_bitrate_kbps, "local-bitrate-kbps")
    validate_bitrate(args.network_bitrate_kbps, "network-bitrate-kbps")
    validate_dimension(args.slice_width, "slice-width")
    validate_dimension(args.slice_height, "slice-height")
    validate_dimension(args.imgsz, "imgsz")
    if not 0 <= args.conf <= 1:
        raise ValueError("conf must be between 0 and 1")
    if not 0 < args.ingest_timeout <= 30:
        raise ValueError("ingest-timeout must be greater than 0 and at most 30 seconds")
    if (args.ingest_url or args.event_ingest_url or args.registration_url) and not args.ingest_token:
        raise ValueError("ingest-token is required when an ingest or registration URL is configured")
    if not 0 <= args.overlap < 1:
        raise ValueError("overlap must be between 0 (inclusive) and 1 (exclusive)")
    if not 1 <= args.sidecar_queue_size <= 65_536:
        raise ValueError("sidecar-queue-size must be between 1 and 65536")
    eos_timeout_seconds = float(getattr(args, "eos_timeout_seconds", 30.0))
    if not 1 <= eos_timeout_seconds <= 300:
        raise ValueError("eos-timeout-seconds must be between 1 and 300")

    key_int = max(1, round(high_fps))
    network_key_int = max(1, round(network_fps))
    high_fps_caps = fps_caps(high_fps)
    network_fps_caps = fps_caps(network_fps)
    # This callback assigns canonical identity and must observe every master
    # frame. Inference dropping occurs later in its size-one worker queue.
    appsink_buffers = 16
    appsink_drop = "drop=false"
    appsink_queue = "queue max-size-buffers=16 max-size-time=0 max-size-bytes=0"
    recovery_file = recovery_file or video_path.with_name(f"{video_path.name}.moov.recovery")
    return f"""
nvarguscamerasrc sensor-id={args.sensor_id} wbmode=1 !
video/x-raw(memory:NVMM),width={high_width},height={high_height},format=NV12,framerate={high_fps_caps} !
tee name=capture
capture. ! queue max-size-buffers=8 max-size-time=0 max-size-bytes=0 !
nvvidconv ! video/x-raw,format=I420,width={high_width},height={high_height} !
x264enc bitrate={args.local_bitrate_kbps} speed-preset=ultrafast tune=zerolatency key-int-max={key_int} bframes=0 !
h264parse ! mp4mux fragment-duration=1000 fragment-mode=first-moov-then-finalise moov-recovery-file={_gst_quote(recovery_file)} ! filesink location={_gst_quote(video_path)}
capture. ! {appsink_queue} !
nvvidconv ! video/x-raw,format=BGRx,width={high_width},height={high_height} !
videoconvert ! video/x-raw,format=BGR,width={high_width},height={high_height} !
appsink name=highres_sink emit-signals=true max-buffers={appsink_buffers} {appsink_drop} sync=false
capture. ! queue max-size-buffers=4 max-size-time=0 max-size-bytes=0 leaky=downstream !
nvvidconv ! video/x-raw,format=I420,width={network_width},height={network_height} !
videorate ! video/x-raw,format=I420,framerate={network_fps_caps} !
x264enc bitrate={args.network_bitrate_kbps} speed-preset=ultrafast tune=zerolatency key-int-max={network_key_int} bframes=0 !
h264parse ! rtph264pay pt={args.payload_type} ssrc={args.rtp_ssrc} config-interval=1 mtu=1200 !
appsink name=network_sink emit-signals=true max-buffers=128 drop=true sync=false
""".strip()


@dataclass
class FramePacket:
    mission_id: str
    capture_epoch: int
    frame_id: int
    camera_id: str
    capture_utc_ns: int
    capture_monotonic_ns: int
    pts_ns: int | None
    image: Any

    @property
    def capture_timestamp(self) -> float:
        return self.capture_utc_ns / 1_000_000_000

    def identity(self) -> dict[str, Any]:
        return {
            "schema_version": "2.0",
            "mission_id": self.mission_id,
            "capture_epoch": self.capture_epoch,
            "frame_id": self.frame_id,
            "camera_id": self.camera_id,
            "capture_utc_ns": self.capture_utc_ns,
            "capture_monotonic_ns": self.capture_monotonic_ns,
            "source_pts_ns": self.pts_ns or 0,
        }


class BoundedSidecarWriter:
    """Move JSON serialization and disk writes off the capture callback."""

    def __init__(
        self,
        args: argparse.Namespace,
        epoch_dir: Path,
        telemetry: MAVLinkTelemetryCollector,
        queue_size: int = 4096,
    ):
        self.args = args
        self.epoch_dir = epoch_dir
        self.telemetry = telemetry
        self.queue: queue.Queue[FramePacket | None] = queue.Queue(maxsize=queue_size)
        self.thread: threading.Thread | None = None
        self.frames_written = 0
        self.telemetry_written = 0
        self.placeholders_written = 0
        self.dropped = 0
        self.error: str | None = None
        self._frames_file = (epoch_dir / "frames.jsonl").open("a", encoding="utf-8", buffering=1)
        self._telemetry_file = (epoch_dir / "telemetry.jsonl").open("a", encoding="utf-8", buffering=1)
        self._detection_file = (
            (epoch_dir / "detections.jsonl").open("a", encoding="utf-8", buffering=1)
            if not args.weights else None
        )

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True, name="jetson-sidecar-writer")
        self.thread.start()

    def submit(self, packet: FramePacket) -> bool:
        try:
            self.queue.put_nowait(packet)
            return True
        except queue.Full:
            self.dropped += 1
            self.error = "sidecar queue overflow; exact per-frame evidence cannot be guaranteed"
            return False

    def close(self) -> None:
        try:
            self.queue.put(None, timeout=5)
        except queue.Full:
            self.error = self.error or "sidecar writer did not drain during shutdown"
        if self.thread:
            self.thread.join(timeout=30)
            if self.thread.is_alive():
                self.error = self.error or "sidecar writer shutdown timeout"
        self._frames_file.close()
        self._telemetry_file.close()
        if self._detection_file is not None:
            self._detection_file.close()

    def metadata(self) -> dict[str, Any]:
        return {
            "queue_depth": self.queue.qsize(),
            "queue_capacity": self.queue.maxsize,
            "frames_written": self.frames_written,
            "telemetry_written": self.telemetry_written,
            "placeholders_written": self.placeholders_written,
            "dropped": self.dropped,
            "error": self.error,
        }

    def _run(self) -> None:
        while True:
            packet = self.queue.get()
            if packet is None:
                return
            try:
                identity = packet.identity()
                frame = {
                    **identity,
                    "type": "frame.capture",
                    "source_width": self.args.high_width,
                    "source_height": self.args.high_height,
                }
                self._frames_file.write(json.dumps(frame, ensure_ascii=False) + "\n")
                self.frames_written += 1
                snapshot = self.telemetry.snapshot(packet.capture_timestamp)
                telemetry = {
                    **identity,
                    "type": "frame.telemetry",
                    "telemetry_source": snapshot["source"],
                    "telemetry_status": snapshot["status"],
                    "telemetry_available": snapshot["connected"],
                    "telemetry_received_at_unix": snapshot["received_at_unix"],
                    "telemetry_age_ms": snapshot["age_ms"],
                    "telemetry_source_error": snapshot["source_error"],
                    "telemetry": snapshot["telemetry"],
                }
                self._telemetry_file.write(json.dumps(telemetry, ensure_ascii=False) + "\n")
                self.telemetry_written += 1
                if self._detection_file is not None:
                    placeholder = {
                        **identity,
                        "type": "vision.frame_result",
                        "detector": {"status": "DISABLED", "reason": "YOLO_DISABLED_CAPTURE_ONLY"},
                        "detections": [],
                        "coordinate": {"status": "not_available"},
                    }
                    self._detection_file.write(json.dumps(placeholder, ensure_ascii=False) + "\n")
                    self.placeholders_written += 1
            except Exception as exc:
                self.error = str(exc)
                print(f"[sidecar] write failed: {exc}", flush=True)


class RtpNetworkSender:
    """Best-effort RTP sender isolated from the local recording pipeline."""

    def __init__(self, host: str, port: int, queue_size: int = 256):
        self.host = host
        self.port = port
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._destination = None
        self._lock = threading.Lock()
        self.packets_sent = 0
        self.packets_dropped = 0
        self.send_error_count = 0
        self.last_error: str | None = None
        self._last_error_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="jetson-rtp-network-sender",
        )
        self._thread.start()

    def submit(self, packet: bytes) -> None:
        if not self._thread or not self._thread.is_alive():
            return
        try:
            self._queue.put_nowait(packet)
        except queue.Full:
            with self._lock:
                self.packets_dropped += 1

    def stop(self) -> None:
        thread = self._thread
        if not thread:
            return
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        thread.join(timeout=3)
        self._stop_event.set()
        if thread.is_alive():
            thread.join(timeout=1)
        self._thread = None

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "RUNNING" if self._thread and self._thread.is_alive() else "STOPPED",
                "host": self.host,
                "port": self.port,
                "transport": "H264/RTP/UDP",
                "packets_sent": self.packets_sent,
                "packets_dropped": self.packets_dropped,
                "send_error_count": self.send_error_count,
                "last_error": self.last_error,
            }

    def _run(self) -> None:
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            while not self._stop_event.is_set():
                packet = self._queue.get()
                if packet is None:
                    return
                if self._destination is None:
                    try:
                        self._destination = socket.getaddrinfo(
                            self.host,
                            self.port,
                            socket.AF_INET,
                            socket.SOCK_DGRAM,
                        )[0][4]
                    except OSError as exc:
                        self._record_error(exc)
                        continue
                try:
                    self._socket.sendto(packet, self._destination)
                    with self._lock:
                        self.packets_sent += 1
                except OSError as exc:
                    self._destination = None
                    with self._lock:
                        self.packets_dropped += 1
                    self._record_error(exc)
        except OSError as exc:
            self._record_error(exc)
        finally:
            if self._socket is not None:
                self._socket.close()
                self._socket = None

    def _record_error(self, error: OSError) -> None:
        now = time.time()
        with self._lock:
            self.send_error_count += 1
            self.last_error = str(error)
        if now - self._last_error_at >= 5:
            print(f"[network] RTP sender unavailable: {error}", flush=True)
            self._last_error_at = now


class MetadataPublisher:
    """Bounded HTTP publisher isolated from capture and inference callbacks."""

    def __init__(self, token: str, timeout: float, queue_size: int = 512):
        self.token = token
        self.timeout = timeout
        self.queue: queue.Queue[tuple[str, str, dict[str, Any]] | None] = queue.Queue(
            maxsize=queue_size
        )
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.sent = 0
        self.errors = 0
        self.dropped = 0
        self.last_error: str | None = None
        self._last_error_at = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="jetson-metadata-publisher")
        self.thread.start()

    def submit(self, kind: str, url: str, payload: dict[str, Any]) -> bool:
        if not url:
            return False
        try:
            self.queue.put_nowait((kind, url, payload))
            return True
        except queue.Full:
            with self._lock:
                self.dropped += 1
            return False

    def close(self) -> None:
        thread = self.thread
        if not thread:
            return
        self.stop_event.set()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(None)
            except queue.Full:
                pass
        thread.join(timeout=max(3.0, self.timeout * 2))
        self.thread = None

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            return {
                "queue_depth": self.queue.qsize(),
                "queue_capacity": self.queue.maxsize,
                "sent": self.sent,
                "errors": self.errors,
                "dropped": self.dropped,
                "dropped_reason": "PUBLISH_QUEUE_FULL" if self.dropped else None,
                "last_error": self.last_error,
            }

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.5)
            except queue.Empty:
                if self.stop_event.is_set():
                    return
                continue
            if item is None:
                return
            kind, url, payload = item
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    if response.status >= 300:
                        raise RuntimeError(f"{kind} ingest HTTP {response.status}")
                with self._lock:
                    self.sent += 1
            except (OSError, URLError, RuntimeError) as exc:
                now = time.monotonic()
                with self._lock:
                    self.errors += 1
                    self.last_error = str(exc)
                if now - self._last_error_at >= 5:
                    print(f"[detector] {kind} ingest unavailable: {exc}", flush=True)
                    self._last_error_at = now


class DetectionRunner:
    """Ultralytics adapter for the frozen non-SAHI production profile."""

    def __init__(self, args: argparse.Namespace, verified_model: VerifiedModel):
        self.args = args
        self.mode = "ultralytics"
        self.verified_model = verified_model
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("YOLO detection requires the Ultralytics package on the Jetson") from exc
        self._model = YOLO(str(verified_model.path))

    def predict(self, image) -> list[dict[str, Any]]:
        results = self._model.predict(
            source=image,
            imgsz=self.args.imgsz,
            conf=self.args.conf,
            device=self.args.device,
            verbose=False,
        )
        result = results[0]
        names = result.names
        detections = []
        for box, confidence, class_id in zip(
            result.boxes.xyxy.tolist(),
            result.boxes.conf.tolist(),
            result.boxes.cls.tolist(),
        ):
            class_id = int(class_id)
            if isinstance(names, dict):
                class_name = names.get(class_id, str(class_id))
            elif isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
                class_name = names[class_id]
            else:
                class_name = str(class_id)
            detections.append({
                "class": str(class_name),
                "confidence": float(confidence),
                "bbox_highres": [float(value) for value in box],
            })
        return detections


class DetectionWorker:
    def __init__(self, args: argparse.Namespace, session_dir: Path, start_timestamp: float):
        self.args = args
        self.session_dir = session_dir
        self.start_timestamp = start_timestamp
        self.queue: queue.Queue[FramePacket | None] = queue.Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self.status = "DISABLED" if not args.weights else "STARTING"
        self.failure_reason: str | None = (
            "YOLO_DISABLED_CAPTURE_ONLY" if not args.weights else None
        )
        self.runner: DetectionRunner | None = None
        self.verified_model: VerifiedModel | None = None
        self.submitted_frames = 0
        self.processed_frames = 0
        self.dropped_oldest = 0
        self.inference_failures = 0
        self.last_inference_ms: float | None = None
        self.failed_at_frame_id: int | None = None
        self.started_monotonic = time.monotonic()
        if args.weights:
            manifest = ProductionModelManifest(args.model_manifest)
            manifest.validate_runtime(
                device=args.device,
                imgsz=args.imgsz,
                confidence=args.conf,
                sahi=args.sahi,
            )
            self.verified_model = manifest.verify(args.weights)
            try:
                self.runner = DetectionRunner(args, self.verified_model)
                self.status = "RUNNING"
            except Exception as exc:
                self.status = "FAILED"
                self.failure_reason = f"DETECTOR_INITIALIZATION_FAILED: {exc}"
        self.detections_path = session_dir / "detections.jsonl"
        self._detection_file = (
            self.detections_path.open("a", encoding="utf-8", buffering=1)
            if args.weights else None
        )
        self.publisher = MetadataPublisher(args.ingest_token, args.ingest_timeout)

    @property
    def needs_image(self) -> bool:
        with self._lock:
            return self.status == "RUNNING" and self.runner is not None

    def start(self) -> None:
        if self.status == "DISABLED":
            return
        self.started_monotonic = time.monotonic()
        self.publisher.start()
        self.thread = threading.Thread(target=self._run, daemon=True, name="jetson-yolo")
        self.thread.start()

    def submit(self, packet: FramePacket) -> None:
        if self.status == "DISABLED":
            # Capture-only placeholders are handled by BoundedSidecarWriter.
            return
        with self._lock:
            self.submitted_frames += 1
        try:
            self.queue.put_nowait(packet)
        except queue.Full:
            try:
                self.queue.get_nowait()
                with self._lock:
                    self.dropped_oldest += 1
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(packet)
            except queue.Full:
                pass

    def close(self) -> None:
        self.stop_event.set()
        try:
            self.queue.put(None, timeout=10)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(None)
            except queue.Full:
                pass
        if self.thread:
            self.thread.join(timeout=10)
        self.publisher.close()
        if self._detection_file is not None:
            self._detection_file.close()

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            elapsed = max(0.001, time.monotonic() - self.started_monotonic)
            return {
                "enabled": bool(self.args.weights),
                "mode": self.runner.mode if self.runner is not None else "none",
                "status": self.status,
                "reason": self.failure_reason,
                "model": self.verified_model.as_dict() if self.verified_model else None,
                "device": self.args.device,
                "imgsz": self.args.imgsz,
                "confidence": self.args.conf,
                "sahi": self.args.sahi,
                "queue_depth": self.queue.qsize(),
                "queue_capacity": self.queue.maxsize,
                "submitted_frames": self.submitted_frames,
                "processed_frames": self.processed_frames,
                "dropped_oldest": self.dropped_oldest,
                "dropped_reason": "INFERENCE_QUEUE_DROP_OLDEST" if self.dropped_oldest else None,
                "inference_failures": self.inference_failures,
                "inference_fps": self.processed_frames / elapsed,
                "last_inference_ms": self.last_inference_ms,
                "failed_at_frame_id": self.failed_at_frame_id,
                "publisher": self.publisher.metadata(),
            }

    def _run(self) -> None:
        while True:
            try:
                packet = self.queue.get(timeout=0.5)
            except queue.Empty:
                if self.stop_event.is_set():
                    return
                continue
            if packet is None:
                return
            detections: list[dict[str, Any]] = []
            inference_started = time.monotonic()
            with self._lock:
                running = self.status == "RUNNING" and self.runner is not None
            if running:
                try:
                    detections = self.runner.predict(packet.image)
                    inference_ms = (time.monotonic() - inference_started) * 1000
                    with self._lock:
                        self.processed_frames += 1
                        self.last_inference_ms = inference_ms
                except Exception as exc:
                    with self._lock:
                        self.status = "FAILED"
                        self.failure_reason = f"INFERENCE_FAILED: {exc}"
                        self.inference_failures += 1
                        self.failed_at_frame_id = packet.frame_id
                    print(f"[detector] frame {packet.frame_id} failed: {exc}", flush=True)

            try:
                for detection in detections:
                    detection["detection_id"] = str(uuid.uuid4())
                    x1, y1, x2, y2 = detection["bbox_highres"]
                    detection["bbox_normalized_xyxy"] = [
                        max(0.0, min(1.0, x1 / self.args.high_width)),
                        max(0.0, min(1.0, y1 / self.args.high_height)),
                        max(0.0, min(1.0, x2 / self.args.high_width)),
                        max(0.0, min(1.0, y2 / self.args.high_height)),
                    ]
                    detection.pop("bbox_highres", None)

                with self._lock:
                    detector_status = self.status
                    detector_reason = self.failure_reason
                payload = {
                    **packet.identity(),
                    "type": "vision.frame_result",
                    "event_id": str(uuid.uuid4()),
                    "source_width": self.args.high_width,
                    "source_height": self.args.high_height,
                    "detector": {
                        "model_id": self.verified_model.model_id if self.verified_model else None,
                        "mode": self.runner.mode if self.runner is not None else "none",
                        "status": detector_status,
                        "reason": detector_reason,
                    },
                    "detections": detections,
                    "coordinate": {"status": "not_available"},
                }
                if self._detection_file is not None:
                    self._detection_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
                if self.args.ingest_url:
                    self.publisher.submit("overlay", self.args.ingest_url, payload)
                if self.args.event_ingest_url:
                    for detection in detections:
                        event = {
                            **packet.identity(),
                            "type": "vision.detection_event",
                            "detection_id": detection["detection_id"],
                            "class": detection["class"],
                            "confidence": detection["confidence"],
                            "bbox_normalized_xyxy": detection["bbox_normalized_xyxy"],
                            "coordinate": {"status": "not_available"},
                        }
                        self.publisher.submit("event", self.args.event_ingest_url, event)
            except Exception as exc:
                with self._lock:
                    self.status = "FAILED"
                    self.failure_reason = f"DETECTION_METADATA_FAILED: {exc}"
                    self.inference_failures += 1
                    self.failed_at_frame_id = packet.frame_id
                print(f"[detector] metadata for frame {packet.frame_id} failed: {exc}", flush=True)


class SplitPipeline:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.storage_info: StorageInfo = validate_record_storage(
            args.record_dir,
            min_free_bytes=args.min_free_bytes,
            mountpoint=args.mountpoint,
            allow_root=args.allow_root_record_dir,
        )
        self.mission_dir, self.session_dir = self._create_session_dir()
        self.video_path = self.session_dir / "video.mp4"
        # Keep mp4mux's recovery index beside the recording on the validated
        # SSD. Fragmented MP4 grows continuously and does not stage the entire
        # recording in /tmp before writing the final moov atom.
        self.recovery_file = self.session_dir / "video.mp4.moov.recovery"
        self.started_at = time.time()
        self.pipeline = None
        self.loop = None
        self.gst = None
        self.glib = None
        self.stopping = False
        self.failure_error: str | None = None
        self.frame_counter = 0
        self.worker: DetectionWorker | None = None
        self.network_sender = RtpNetworkSender(args.host, args.port)
        self._identity_condition = threading.Condition()
        self._identity_by_pts: OrderedDict[int, int] = OrderedDict()
        self._identity_miss_count = 0
        self._registration_stop = threading.Event()
        self._registration_thread: threading.Thread | None = None
        self.telemetry = MAVLinkTelemetryCollector()
        self.sidecars = BoundedSidecarWriter(
            args, self.session_dir, self.telemetry, queue_size=args.sidecar_queue_size
        )
        self._telemetry_started = False
        self._write_metadata("STARTING")
        try:
            # Validate all CLI/GStreamer properties before loading a model.
            build_pipeline_description(args, self.video_path, self.recovery_file)
            self.worker = DetectionWorker(args, self.session_dir, self.started_at)
        except Exception as exc:
            self.sidecars.close()
            self._write_metadata("FAILED", error=str(exc))
            raise

    def _create_session_dir(self) -> tuple[Path, Path]:
        root = Path(self.args.record_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        mission_id = self.args.mission_id or f"mission-{uuid.uuid4()}"
        if not re.fullmatch(r"mission-[0-9a-fA-F-]{36}", mission_id):
            raise ValueError("mission-id must be mission-<uuid>")
        try:
            uuid.UUID(mission_id.removeprefix("mission-"))
        except ValueError as exc:
            raise ValueError("mission-id must be mission-<uuid>") from exc
        if self.args.capture_epoch < 1:
            raise ValueError("capture-epoch must be at least 1")
        self.args.mission_id = mission_id
        mission_dir = root / mission_id
        mission_dir.mkdir(parents=True, exist_ok=True)
        (mission_dir / "epochs").mkdir(exist_ok=True)
        manifest_path = mission_dir / "mission.json"
        if not manifest_path.exists():
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "2.0",
                        "mission_id": mission_id,
                        "camera_id": "arducam",
                        "status": "RECORDING",
                        "current_epoch": self.args.capture_epoch,
                        "created_utc_ns": time.time_ns(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        epoch_dir = mission_dir / "epochs" / f"{self.args.capture_epoch:04d}"
        epoch_dir.mkdir(parents=True, exist_ok=False)
        return mission_dir, epoch_dir

    def run(self) -> int:
        try:
            self.telemetry.start()
            self._telemetry_started = True
            try:
                import gi

                gi.require_version("Gst", "1.0")
                gi.require_version("GLib", "2.0")
                from gi.repository import GLib, Gst
            except ImportError as exc:
                raise RuntimeError("Jetson sender requires PyGObject/GStreamer Python bindings") from exc

            self.gst = Gst
            self.glib = GLib
            Gst.init(None)
            description = build_pipeline_description(self.args, self.video_path, self.recovery_file)
            print("[pipeline] high-res recording and low-res RTP branches enabled", flush=True)
            print(f"[pipeline] local={self.args.high_width}x{self.args.high_height}@{self.args.high_fps:g}", flush=True)
            print(f"[pipeline] network={self.args.network_width}x{self.args.network_height}@{self.args.network_fps:g} -> {self.args.host}:{self.args.port}", flush=True)
            self.pipeline = Gst.parse_launch(description)
            sink = self.pipeline.get_by_name("highres_sink")
            if sink is None:
                raise RuntimeError("GStreamer pipeline did not create highres_sink")
            sink.connect("new-sample", self._on_sample)
            network_sink = self.pipeline.get_by_name("network_sink")
            if network_sink is None:
                raise RuntimeError("GStreamer pipeline did not create network_sink")
            network_sink.connect("new-sample", self._on_network_sample)

            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_message)
            if self.worker is None:
                raise RuntimeError("Detection worker was not initialized")
            self.sidecars.start()
            self.worker.start()
            self.network_sender.start()
            self._start_registration_publisher()
            self.pipeline.set_state(Gst.State.PLAYING)
            self._write_metadata("RECORDING")
            self.loop = GLib.MainLoop()
            self.glib.timeout_add(1000, self._publish_runtime_metadata)
            self.loop.run()
            return 1 if self.failure_error else 0
        except Exception as exc:
            self.failure_error = str(exc)
            raise
        finally:
            self._shutdown_pipeline()
            self._stop_registration_publisher()
            self.network_sender.stop()
            if self.worker is not None:
                self.worker.close()
            self.sidecars.close()
            if self.sidecars.error and not self.failure_error:
                self.failure_error = self.sidecars.error
            if self._telemetry_started:
                self.telemetry.stop()
                self._telemetry_started = False
            if not self.failure_error:
                self.failure_error = self._validate_video_output()
            if not self.failure_error:
                try:
                    self.recovery_file.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    print(f"[pipeline] could not remove MP4 recovery file: {exc}", flush=True)
            if self.failure_error:
                self._write_metadata("FAILED", error=self.failure_error)
            elif self.pipeline is not None:
                self._write_metadata("COMPLETED")

    def request_stop(self, *_args) -> None:
        if self.stopping:
            return
        self.stopping = True
        if self.pipeline is None:
            if self.loop and self.loop.is_running():
                self.loop.quit()
            return
        print("[pipeline] stopping with EOS", flush=True)
        self.pipeline.send_event(self.gst.Event.new_eos())
        if self.glib:
            self.glib.timeout_add(
                int(self.args.eos_timeout_seconds * 1000),
                self._force_quit,
            )

    def _force_quit(self):
        if self.loop and self.loop.is_running():
            print("[pipeline] EOS timeout; forcing shutdown", flush=True)
            self.loop.quit()
        return False

    def _publish_runtime_metadata(self):
        if self.stopping or self.failure_error:
            return False
        self._write_metadata("RECORDING")
        return bool(self.loop and self.loop.is_running())

    def _on_message(self, _bus, message) -> None:
        message_type = message.type
        if message_type == self.gst.MessageType.ERROR:
            error, debug = message.parse_error()
            print(f"[pipeline] ERROR: {error} ({debug or 'no debug'})", flush=True)
            self.failure_error = str(error)
            if self.loop and self.loop.is_running():
                self.loop.quit()
        elif message_type == self.gst.MessageType.EOS:
            if self.loop and self.loop.is_running():
                self.loop.quit()
        elif message_type == self.gst.MessageType.WARNING:
            warning, debug = message.parse_warning()
            print(f"[pipeline] WARNING: {warning} ({debug or 'no debug'})", flush=True)

    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return self.gst.FlowReturn.ERROR
        buffer = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        width = caps.get_value("width")
        height = caps.get_value("height")

        pts = None if buffer.pts == self.gst.CLOCK_TIME_NONE else int(buffer.pts)
        frame_id = self.frame_counter
        self.frame_counter += 1
        capture_utc_ns = time.time_ns()
        capture_monotonic_ns = time.monotonic_ns()
        if pts is not None:
            with self._identity_condition:
                self._identity_by_pts[pts] = frame_id
                self._identity_by_pts.move_to_end(pts)
                while len(self._identity_by_pts) > 512:
                    self._identity_by_pts.popitem(last=False)
                self._identity_condition.notify_all()
        # Capture-only mode does not need to copy a 4K BGR frame into Python.
        # The appsink still gives us the source PTS, so telemetry and the
        # explicit empty detection record remain aligned with video.mp4.
        image = None
        if self.worker is not None and self.worker.needs_image:
            success, map_info = buffer.map(self.gst.MapFlags.READ)
            if not success:
                return self.gst.FlowReturn.ERROR
            try:
                import numpy as np

                image = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3)).copy()
            finally:
                buffer.unmap(map_info)

        packet = FramePacket(
            mission_id=self.args.mission_id,
            capture_epoch=self.args.capture_epoch,
            frame_id=frame_id,
            camera_id="arducam",
            capture_utc_ns=capture_utc_ns,
            capture_monotonic_ns=capture_monotonic_ns,
            pts_ns=pts,
            image=image,
        )
        if not self.sidecars.submit(packet):
            self.failure_error = self.sidecars.error
            if self.loop and self.loop.is_running():
                self.glib.idle_add(self.loop.quit)
        if self.worker is not None:
            self.worker.submit(packet)
        return self.gst.FlowReturn.OK

    def _on_network_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return self.gst.FlowReturn.ERROR
        buffer = sample.get_buffer()
        success, map_info = buffer.map(self.gst.MapFlags.READ)
        if not success:
            return self.gst.FlowReturn.OK
        try:
            # Only enqueue the already-packetized RTP datagram. No socket
            # operation occurs in the GStreamer streaming callback, so a
            # disconnected Tailscale/network path cannot block the local
            # recording branch.
            pts = None if buffer.pts == self.gst.CLOCK_TIME_NONE else int(buffer.pts)
            frame_id = self._wait_for_frame_id(pts)
            if frame_id is None:
                self._identity_miss_count += 1
                return self.gst.FlowReturn.OK
            try:
                packet = inject_frame_id(bytes(map_info.data), frame_id)
            except RtpIdentityError as exc:
                self._identity_miss_count += 1
                print(f"[network] RTP identity injection failed: {exc}", flush=True)
                return self.gst.FlowReturn.OK
            self.network_sender.submit(packet)
        finally:
            buffer.unmap(map_info)
        return self.gst.FlowReturn.OK

    def _wait_for_frame_id(self, pts: int | None) -> int | None:
        if pts is None:
            return None
        deadline = time.monotonic() + 0.05
        with self._identity_condition:
            while pts not in self._identity_by_pts:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._identity_condition.wait(remaining)
            return self._identity_by_pts[pts]

    def _start_registration_publisher(self) -> None:
        if not self.args.registration_url:
            return
        self._registration_stop.clear()
        self._registration_thread = threading.Thread(
            target=self._registration_loop, daemon=True, name="jetson-stream-registration"
        )
        self._registration_thread.start()

    def _stop_registration_publisher(self) -> None:
        self._registration_stop.set()
        if self._registration_thread:
            self._registration_thread.join(timeout=2)
            self._registration_thread = None

    def _registration_loop(self) -> None:
        payload = {
            "schema_version": "2.0",
            "mission_id": self.args.mission_id,
            "capture_epoch": self.args.capture_epoch,
            "camera_id": "arducam",
            "ssrc": self.args.rtp_ssrc,
            "width": self.args.network_width,
            "height": self.args.network_height,
            "fps": self.args.network_fps,
            "rtp_clock_rate": 90_000,
        }
        while not self._registration_stop.is_set():
            request = Request(
                self.args.registration_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.args.ingest_token}",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.args.ingest_timeout) as response:
                    if response.status >= 300:
                        raise RuntimeError(f"registration HTTP {response.status}")
            except (OSError, URLError, RuntimeError) as exc:
                print(f"[network] stream registration unavailable: {exc}", flush=True)
            self._registration_stop.wait(5)

    def _shutdown_pipeline(self) -> None:
        if self.pipeline is not None:
            self.pipeline.set_state(self.gst.State.NULL)

    def _validate_video_output(self) -> str | None:
        """Reject a nominally completed session with an empty/invalid MP4."""

        try:
            size = self.video_path.stat().st_size
            if size <= 0:
                return "video.mp4 is empty after pipeline shutdown"
            if self.frame_counter <= 0:
                return "video.mp4 finalized without captured frames"
            with self.video_path.open("rb") as handle:
                head = handle.read(1024 * 1024)
                if size > 8 * 1024 * 1024:
                    handle.seek(max(0, size - 8 * 1024 * 1024))
                tail = handle.read(8 * 1024 * 1024)
        except OSError as exc:
            return f"cannot validate video.mp4: {exc}"

        if b"ftyp" not in head:
            return "video.mp4 is missing the MP4 ftyp atom"
        if b"moov" not in head and b"moov" not in tail:
            return "video.mp4 is missing the MP4 moov atom"
        if b"moof" not in head and b"moof" not in tail:
            return "video.mp4 is missing fragmented MP4 media atoms"
        return None

    def _write_metadata(self, status: str, error: str | None = None) -> None:
        try:
            usage = shutil.disk_usage(self.session_dir)
            video_size = self.video_path.stat().st_size if self.video_path.exists() else 0
            recovery_size = self.recovery_file.stat().st_size if self.recovery_file.exists() else 0
            storage = {
                **self.storage_info.as_dict(),
                "free_bytes": usage.free,
                "used_bytes": usage.used,
                "video_size_bytes": video_size,
                "recovery_file_size_bytes": recovery_size,
            }
        except OSError as exc:
            storage = {**self.storage_info.as_dict(), "error": str(exc)}
        metadata = {
            "schema_version": "2.0",
            "mission_id": self.args.mission_id,
            "capture_epoch": self.args.capture_epoch,
            "camera_id": "arducam",
            "label": self.args.label,
            "status": status,
            "frame_count": self.frame_counter,
            "started_at": utc_iso(self.started_at),
            "ended_at": utc_iso(time.time()) if status in {"COMPLETED", "FAILED"} else None,
            "highres": {
                "width": self.args.high_width,
                "height": self.args.high_height,
                "fps": self.args.high_fps,
                "purpose": ["local_recording", "offline_yolo"],
            },
            "network": {
                "width": self.args.network_width,
                "height": self.args.network_height,
                "fps": self.args.network_fps,
                "host": self.args.host,
                "port": self.args.port,
                "payload_type": self.args.payload_type,
                "transport": "H264/RTP/UDP (best-effort sender)",
            },
            "network_sender": self.network_sender.metadata(),
            "files": {
                "video": "video.mp4",
                "video_recovery_file": "video.mp4.moov.recovery",
                "frames": "frames.jsonl",
                "telemetry": "telemetry.jsonl",
                "detections": "detections.jsonl",
            },
            "storage": storage,
            "frame_identity": {
                "key": ["mission_id", "capture_epoch", "frame_id", "camera_id"],
                "source_pts_field": "source_pts_ns",
                "description": "identity is assigned in the source callback before recording metadata, inference, and preview publication",
            },
            "detector": self.worker.metadata() if self.worker is not None else {
                "enabled": False,
                "mode": "none",
                "status": "DISABLED",
                "reason": "YOLO_DISABLED_CAPTURE_ONLY",
            },
            "telemetry": self.telemetry.metadata(),
            "health": {
                "capture_fps": self.frame_counter / max(0.001, time.time() - self.started_at),
                "sidecar": self.sidecars.metadata(),
                "inference": self.worker.metadata() if self.worker is not None else None,
                "dropped_preview_packets": self.network_sender.packets_dropped,
                "dropped_preview_identity_missing": self._identity_miss_count,
                "storage_rate_bytes_per_second": video_size / max(0.001, time.time() - self.started_at),
                **read_system_health(),
            },
            "error": error,
        }
        temporary = self.session_dir / "epoch.json.tmp"
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.session_dir / "epoch.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="GCS Tailscale IP or hostname")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--payload-type", type=int, default=96)
    parser.add_argument("--rtp-ssrc", type=int, default=uuid.uuid4().int & 0xFFFFFFFF)
    parser.add_argument("--sensor-id", type=int, default=0)
    parser.add_argument("--high-width", type=int, default=1920)
    parser.add_argument("--high-height", type=int, default=1080)
    parser.add_argument("--high-fps", type=float, default=30.0)
    parser.add_argument("--network-width", type=int, default=960)
    parser.add_argument("--network-height", type=int, default=540)
    parser.add_argument("--network-fps", type=float, default=15.0)
    parser.add_argument("--local-bitrate-kbps", type=int, default=12000)
    parser.add_argument("--network-bitrate-kbps", type=int, default=2000)
    parser.add_argument("--record-dir", type=Path, default=Path("recordings"))
    parser.add_argument(
        "--mountpoint",
        type=Path,
        default=None,
        help="Expected mounted filesystem containing --record-dir",
    )
    parser.add_argument(
        "--min-free-bytes",
        type=int,
        default=10 * 1024**3,
        help="Minimum free bytes required before recording",
    )
    parser.add_argument(
        "--allow-root-record-dir",
        action="store_true",
        help="Allow recording on the root filesystem for development only",
    )
    parser.add_argument(
        "--eos-timeout-seconds",
        type=float,
        default=30.0,
        help="Maximum time to wait for MP4 EOS/finalization",
    )
    parser.add_argument("--mission-id")
    parser.add_argument("--capture-epoch", type=int, default=1)
    parser.add_argument("--sidecar-queue-size", type=int, default=4096)
    parser.add_argument("--label")
    parser.add_argument("--weights", help="YOLO/SAHI model path; omit to run capture-only")
    parser.add_argument(
        "--model-manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Frozen production checkpoint manifest",
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.45)
    parser.add_argument("--sahi", action="store_true")
    parser.add_argument("--sahi-standard-pred", action="store_true")
    parser.add_argument("--slice-width", type=int, default=640)
    parser.add_argument("--slice-height", type=int, default=640)
    parser.add_argument("--overlap", type=float, default=0.2)
    parser.add_argument("--ingest-url", default="")
    parser.add_argument("--event-ingest-url", default="")
    parser.add_argument("--registration-url", default="")
    parser.add_argument("--ingest-token", default="")
    parser.add_argument("--ingest-timeout", type=float, default=0.5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pipeline: SplitPipeline | None = None
    try:
        pipeline = SplitPipeline(args)
        signal.signal(signal.SIGINT, pipeline.request_stop)
        signal.signal(signal.SIGTERM, pipeline.request_stop)
        return pipeline.run()
    except Exception as exc:
        if pipeline is not None:
            pipeline._write_metadata("FAILED", error=str(exc))
        traceback.print_exc()
        print(f"[pipeline] fatal: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
