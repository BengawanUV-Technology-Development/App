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
the footage immediately usable for offline YOLO and coordinate reconstruction
without pretending that a detector or telemetry source was active.

Orin Nano does not provide NVENC, so x264enc is used deliberately. Start with
1920x1080 for the high-resolution branch and benchmark CPU/FPS before trying a
higher source mode.
"""

from __future__ import annotations

import argparse
import json
import queue
import re
import signal
import shutil
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

try:
    from .mavlink_telemetry import MAVLinkTelemetryCollector
    from .storage_guard import StorageInfo, validate_record_storage
except ImportError:  # Script execution from the Jetson service directory.
    from mavlink_telemetry import MAVLinkTelemetryCollector
    from storage_guard import StorageInfo, validate_record_storage


def utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


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
    if not 0 <= args.overlap < 1:
        raise ValueError("overlap must be between 0 (inclusive) and 1 (exclusive)")
    eos_timeout_seconds = float(getattr(args, "eos_timeout_seconds", 30.0))
    if not 1 <= eos_timeout_seconds <= 300:
        raise ValueError("eos-timeout-seconds must be between 1 and 300")

    key_int = max(1, round(high_fps))
    network_key_int = max(1, round(network_fps))
    high_fps_caps = fps_caps(high_fps)
    network_fps_caps = fps_caps(network_fps)
    appsink_buffers = 1 if args.weights else 16
    appsink_drop = "drop=true" if args.weights else "drop=false"
    appsink_queue = (
        "queue max-size-buffers=2 max-size-time=0 max-size-bytes=0 leaky=downstream"
        if args.weights
        else "queue max-size-buffers=16 max-size-time=0 max-size-bytes=0"
    )
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
h264parse ! rtph264pay pt={args.payload_type} config-interval=1 mtu=1200 !
appsink name=network_sink emit-signals=true max-buffers=128 drop=true sync=false
""".strip()


@dataclass
class FramePacket:
    frame_id: int
    capture_timestamp: float
    pts_ns: int | None
    image: Any


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
                "status": "ACTIVE" if self._thread and self._thread.is_alive() else "STOPPED",
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


class DetectionRunner:
    """Lazy YOLO/SAHI adapter so the capture pipeline can run without a model."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.mode = "none"
        self._model = None
        self._sahi_model = None
        if not args.weights:
            return

        if args.sahi:
            try:
                from sahi import AutoDetectionModel
            except ImportError as exc:
                raise RuntimeError("--sahi requires the SAHI package on the Jetson") from exc
            self._sahi_model = AutoDetectionModel.from_pretrained(
                model_type="ultralytics",
                model_path=args.weights,
                confidence_threshold=args.conf,
                device=args.device,
            )
            self.mode = "sahi"
        else:
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError("YOLO detection requires the Ultralytics package on the Jetson") from exc
            self._model = YOLO(args.weights)
            self.mode = "ultralytics"

    def predict(self, image) -> list[dict[str, Any]]:
        if self.mode == "none":
            return []
        if self.mode == "sahi":
            from sahi.predict import get_sliced_prediction

            result = get_sliced_prediction(
                image,
                self._sahi_model,
                slice_height=self.args.slice_height,
                slice_width=self.args.slice_width,
                overlap_height_ratio=self.args.overlap,
                overlap_width_ratio=self.args.overlap,
                perform_standard_pred=self.args.sahi_standard_pred,
            )
            detections = []
            for prediction in result.object_prediction_list:
                x1, y1, x2, y2 = prediction.bbox.to_xyxy()
                detections.append({
                    "class": prediction.category.name,
                    "confidence": float(prediction.score.value),
                    "bbox_highres": [float(x1), float(y1), float(x2), float(y2)],
                })
            return detections

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
        self.runner = DetectionRunner(args)
        self.detections_path = session_dir / "detections.jsonl"
        self._detection_file = self.detections_path.open("a", encoding="utf-8", buffering=1)
        self._last_post_error_at = 0.0

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True, name="jetson-yolo-sahi")
        self.thread.start()

    def submit(self, packet: FramePacket) -> None:
        if self.runner.mode == "none":
            # The capture-only contract must have one sidecar row per frame.
            # Write it synchronously instead of allowing a detector queue to
            # drop rows under load. No overlay HTTP request is made in this
            # mode because an empty detection is not a live detection event.
            self._write_placeholder(packet)
            return
        try:
            self.queue.put_nowait(packet)
        except queue.Full:
            try:
                self.queue.get_nowait()
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
        self._detection_file.close()

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
            try:
                detections = self.runner.predict(packet.image)
                for detection in detections:
                    detection["bbox_network"] = scale_bbox(
                        detection["bbox_highres"],
                        self.args.high_width,
                        self.args.high_height,
                        self.args.network_width,
                        self.args.network_height,
                    )
                    detection["bbox_norm_highres"] = [
                        detection["bbox_highres"][0] / self.args.high_width,
                        detection["bbox_highres"][1] / self.args.high_height,
                        detection["bbox_highres"][2] / self.args.high_width,
                        detection["bbox_highres"][3] / self.args.high_height,
                    ]

                payload = {
                    "schema_version": "1.1",
                    "type": "vision.overlay",
                    "session_id": self.session_dir.name,
                    "detection_id": f"FRAME-{packet.frame_id}-{uuid.uuid4().hex[:8]}",
                    "timestamp": utc_iso(time.time()),
                    "frame_id": packet.frame_id,
                    "frame_timestamp": utc_iso(packet.capture_timestamp),
                    "pts_ns": packet.pts_ns,
                    "source_width": self.args.high_width,
                    "source_height": self.args.high_height,
                    "network_width": self.args.network_width,
                    "network_height": self.args.network_height,
                    "detector": {
                        "enabled": self.runner.mode != "none",
                        "mode": self.runner.mode,
                        "status": "DISABLED" if self.runner.mode == "none" else "ACTIVE",
                        "reason": "YOLO_DISABLED_CAPTURE_ONLY" if self.runner.mode == "none" else None,
                    },
                    "bbox": detections[0].get("bbox_highres") if len(detections) == 1 else None,
                    "detections": detections,
                    "coordinate": {
                        "status": "UNAVAILABLE",
                        "latitude": None,
                        "longitude": None,
                        "error_radius_m": None,
                    },
                }
                self._detection_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
                if self.args.ingest_url:
                    self._post_overlay(payload)
            except Exception as exc:
                print(f"[detector] frame {packet.frame_id} failed: {exc}", flush=True)

    def _write_placeholder(self, packet: FramePacket) -> None:
        payload = {
            "schema_version": "1.1",
            "type": "vision.overlay",
            "session_id": self.session_dir.name,
            "detection_id": f"FRAME-{packet.frame_id}-{uuid.uuid4().hex[:8]}",
            "timestamp": utc_iso(time.time()),
            "frame_id": packet.frame_id,
            "frame_timestamp": utc_iso(packet.capture_timestamp),
            "pts_ns": packet.pts_ns,
            "source_width": self.args.high_width,
            "source_height": self.args.high_height,
            "network_width": self.args.network_width,
            "network_height": self.args.network_height,
            "detector": {
                "enabled": False,
                "mode": "none",
                "status": "DISABLED",
                "reason": "YOLO_DISABLED_CAPTURE_ONLY",
            },
            "bbox": None,
            "detections": [],
            "coordinate": {
                "status": "UNAVAILABLE",
                "latitude": None,
                "longitude": None,
                "error_radius_m": None,
            },
        }
        self._detection_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _post_overlay(self, payload: dict[str, Any]) -> None:
        request = Request(
            self.args.ingest_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.args.ingest_timeout) as response:
                if response.status >= 300:
                    raise RuntimeError(f"overlay ingest HTTP {response.status}")
        except (OSError, URLError, RuntimeError) as exc:
            now = time.time()
            if now - self._last_post_error_at >= 5:
                print(f"[detector] overlay ingest unavailable: {exc}", flush=True)
                self._last_post_error_at = now


class SplitPipeline:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.storage_info: StorageInfo = validate_record_storage(
            args.record_dir,
            min_free_bytes=args.min_free_bytes,
            mountpoint=args.mountpoint,
            allow_root=args.allow_root_record_dir,
        )
        self.session_dir = self._create_session_dir()
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
        self.first_pts_ns: int | None = None
        self.last_frame_id = -1
        self.worker: DetectionWorker | None = None
        self.network_sender = RtpNetworkSender(args.host, args.port)
        self.telemetry = MAVLinkTelemetryCollector()
        self.telemetry_path = self.session_dir / "telemetry.jsonl"
        self._telemetry_file = None
        self._started_monotonic = time.monotonic()
        self._telemetry_started = False
        try:
            self._telemetry_file = self.telemetry_path.open(
                "a", encoding="utf-8", buffering=1
            )
        except Exception as exc:
            self._write_metadata("FAILED", error=str(exc))
            raise
        self._write_metadata("STARTING")
        try:
            # Validate all CLI/GStreamer properties before loading a model.
            build_pipeline_description(args, self.video_path, self.recovery_file)
            self.worker = DetectionWorker(args, self.session_dir, self.started_at)
        except Exception as exc:
            self._close_telemetry_file()
            self._write_metadata("FAILED", error=str(exc))
            raise

    def _create_session_dir(self) -> Path:
        root = Path(self.args.record_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        session_id = self.args.session_id or f"flight-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        path = root / session_id
        path.mkdir(parents=True, exist_ok=False)
        return path

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
            self.worker.start()
            self.network_sender.start()
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
            self.network_sender.stop()
            if self.worker is not None:
                self.worker.close()
            if self._telemetry_started:
                self.telemetry.stop()
                self._telemetry_started = False
            self._close_telemetry_file()
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
        if pts is None:
            capture_timestamp = time.time()
        else:
            if self.first_pts_ns is None:
                self.first_pts_ns = pts
            elapsed_seconds = max(0.0, (pts - self.first_pts_ns) / self.gst.SECOND)
            capture_timestamp = self.started_at + elapsed_seconds
        if self.args.weights:
            # Detector mode may intentionally drop appsink samples; retain a
            # PTS-derived identity for the sampled frame in that mode.
            elapsed_seconds = (
                0.0
                if pts is None or self.first_pts_ns is None
                else max(0.0, (pts - self.first_pts_ns) / self.gst.SECOND)
            )
            frame_id = max(self.last_frame_id + 1, round(elapsed_seconds * self.args.high_fps))
        else:
            # Capture-only mode uses a lossless appsink branch, so this is the
            # exact frame index used by video.mp4 and both sidecars.
            frame_id = self.frame_counter
        self.frame_counter += 1
        self.last_frame_id = frame_id
        # Capture-only mode does not need to copy a 4K BGR frame into Python.
        # The appsink still gives us the source PTS, so telemetry and the
        # explicit empty detection record remain aligned with video.mp4.
        image = None
        if self.worker is not None and self.worker.runner.mode != "none":
            success, map_info = buffer.map(self.gst.MapFlags.READ)
            if not success:
                return self.gst.FlowReturn.ERROR
            try:
                import numpy as np

                image = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3)).copy()
            finally:
                buffer.unmap(map_info)

        packet = FramePacket(frame_id, capture_timestamp, pts, image)
        self._write_telemetry(packet)
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
            self.network_sender.submit(bytes(map_info.data))
        finally:
            buffer.unmap(map_info)
        return self.gst.FlowReturn.OK

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

    def _close_telemetry_file(self) -> None:
        if self._telemetry_file is not None:
            self._telemetry_file.close()
            self._telemetry_file = None

    def _write_telemetry(self, packet: FramePacket) -> None:
        if self._telemetry_file is None:
            return
        snapshot = self.telemetry.snapshot(packet.capture_timestamp)
        row = {
            "schema_version": "1.1",
            "type": "frame.telemetry",
            "session_id": self.session_dir.name,
            "frame_id": packet.frame_id,
            "pts_ns": packet.pts_ns,
            "captured_at_unix": packet.capture_timestamp,
            "captured_at_iso": utc_iso(packet.capture_timestamp),
            "capture_timestamp_ns": int(packet.capture_timestamp * 1_000_000_000),
            "elapsed_monotonic_seconds": time.monotonic() - self._started_monotonic,
            "telemetry_source": snapshot["source"],
            "telemetry_status": snapshot["status"],
            "telemetry_available": snapshot["connected"],
            "telemetry_received_at_unix": snapshot["received_at_unix"],
            "telemetry_age_ms": snapshot["age_ms"],
            "telemetry_source_error": snapshot["source_error"],
            "telemetry": snapshot["telemetry"],
        }
        self._telemetry_file.write(json.dumps(row, ensure_ascii=False) + "\n")

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
            "schema_version": "1.1",
            "session_id": self.session_dir.name,
            "label": self.args.label,
            "status": status,
            "frame_count": self.frame_counter,
            "started_at": utc_iso(self.started_at),
            "ended_at": utc_iso(time.time()) if status in {"COMPLETED", "FAILED"} else None,
            "highres": {
                "width": self.args.high_width,
                "height": self.args.high_height,
                "fps": self.args.high_fps,
                "purpose": ["local_recording", "offline_yolo", "coordinate_reconstruction"],
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
                "telemetry": "telemetry.jsonl",
                "detections": "detections.jsonl",
            },
            "storage": storage,
            "frame_identity": {
                "source": "Sequential source callback index in capture-only mode; PTS is retained for timing",
                "field": "frame_id",
                "pts_field": "pts_ns",
                "description": "capture-only frame_id is zero-based and lossless with video.mp4; detector mode may use a PTS-derived sampled identity",
            },
            "detector": {
                "enabled": bool(self.args.weights),
                "mode": self.worker.runner.mode if self.worker is not None else "none",
                "status": "DISABLED" if not self.args.weights else "ACTIVE",
                "reason": "YOLO_DISABLED_CAPTURE_ONLY" if not self.args.weights else None,
                "weights": self.args.weights,
                "sahi": self.args.sahi,
                "confidence": self.args.conf,
            },
            "telemetry": self.telemetry.metadata(),
            "error": error,
        }
        temporary = self.session_dir / "metadata.json.tmp"
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.session_dir / "metadata.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="GCS Tailscale IP or hostname")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--payload-type", type=int, default=96)
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
    parser.add_argument("--session-id")
    parser.add_argument("--label")
    parser.add_argument("--weights", help="YOLO/SAHI model path; omit to run capture-only")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.45)
    parser.add_argument("--sahi", action="store_true")
    parser.add_argument("--sahi-standard-pred", action="store_true")
    parser.add_argument("--slice-width", type=int, default=640)
    parser.add_argument("--slice-height", type=int, default=640)
    parser.add_argument("--overlap", type=float, default=0.2)
    parser.add_argument("--ingest-url", default="")
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
        print(f"[pipeline] fatal: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
