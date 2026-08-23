"""Receive the Jetson H.264/RTP preview and publish it as MJPEG.

The Jetson sends a low-resolution preview over RTP/UDP.  This service owns
only the receive/decode side: it never opens a camera device and never sends
anything to the flight controller.  GStreamer is loaded lazily so the
telemetry backend can still start on machines where the optional video
dependencies are not installed.
"""

from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Iterator


class CameraStreamError(RuntimeError):
    """Raised when the RTP receiver cannot be configured or started."""


class CameraStreamService:
    """Decode one Jetson RTP stream and expose the latest JPEG frames."""

    def __init__(self) -> None:
        self.bind_address = os.getenv("JETSON_VIDEO_BIND_ADDRESS", "0.0.0.0")
        try:
            ipaddress.ip_address(self.bind_address)
        except ValueError as exc:
            raise CameraStreamError(
                "JETSON_VIDEO_BIND_ADDRESS must be a valid IP address"
            ) from exc

        self.port = self._env_int("JETSON_VIDEO_PORT", 5000, 1, 65535)
        self.payload_type = self._env_int("JETSON_VIDEO_PAYLOAD_TYPE", 96, 0, 127)
        self.jitter_latency_ms = self._env_int(
            "JETSON_VIDEO_JITTER_LATENCY_MS", 80, 0, 5000
        )
        self.width = self._env_int("JETSON_VIDEO_PREVIEW_WIDTH", 960, 16, 7680)
        self.height = self._env_int("JETSON_VIDEO_PREVIEW_HEIGHT", 540, 16, 4320)
        self.expected_fps = self._env_float("JETSON_VIDEO_FPS", 15.0, 0.1, 240.0)
        self.frame_timeout_seconds = self._env_float(
            "JETSON_VIDEO_FRAME_TIMEOUT_SECONDS", 5.0, 0.5, 60.0
        )
        self.jpeg_quality = self._env_int(
            "JETSON_VIDEO_PREVIEW_JPEG_QUALITY", 75, 1, 100
        )
        self.decoder = os.getenv("JETSON_VIDEO_DECODER", "avdec_h264").strip()
        if not self.decoder or not re.fullmatch(r"[A-Za-z0-9_-]+", self.decoder):
            raise CameraStreamError(
                "JETSON_VIDEO_DECODER must be one GStreamer element name"
            )

        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pipeline = None
        self._loop = None
        self._gst = None
        self._latest_jpeg: bytes | None = None
        self._preview_version = 0
        self._frame_times: deque[float] = deque(maxlen=60)
        self._state = self._empty_state()

    @staticmethod
    def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError as exc:
            raise CameraStreamError(f"{name} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise CameraStreamError(f"{name} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(os.getenv(name, str(default)))
        except ValueError as exc:
            raise CameraStreamError(f"{name} must be a number") from exc
        if not minimum <= value <= maximum:
            raise CameraStreamError(f"{name} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _empty_state() -> dict:
        return {
            "camera_source": "jetson_udp",
            "camera_running": False,
            "camera_status": "STOPPED",
            "camera_error": None,
            "width": None,
            "height": None,
            "fps": 0.0,
            "expected_fps": None,
            "frame_count": 0,
            "last_frame_timestamp": None,
            "last_frame_at_unix": None,
            "stream_port": None,
            "payload_type": None,
            "decoder": None,
            "transport": "H264/RTP/UDP",
        }

    def build_pipeline(self) -> str:
        """Return the low-latency GStreamer receiver pipeline."""

        caps = (
            "application/x-rtp,media=video,clock-rate=90000,"
            f"encoding-name=H264,payload={self.payload_type}"
        )
        return (
            f'udpsrc name=rtp_source address="{self.bind_address}" port={self.port} '
            f'caps="{caps}" ! '
            f"rtpjitterbuffer name=rtp_jitter latency={self.jitter_latency_ms} "
            "drop-on-latency=true ! rtph264depay ! h264parse ! "
            f"{self.decoder} ! videoconvert ! videoscale ! "
            f"video/x-raw,format=I420,width={self.width},height={self.height} ! "
            f"jpegenc quality={self.jpeg_quality} ! "
            "appsink name=jpeg_sink emit-signals=true max-buffers=4 "
            "drop=true sync=false"
        )

    @staticmethod
    def _load_gst():
        try:
            import gi

            gi.require_version("Gst", "1.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import GLib, Gst
        except (ImportError, ValueError) as exc:
            raise CameraStreamError(
                "PyGObject and GStreamer 1.0 are required for the camera preview"
            ) from exc
        Gst.init([])
        return Gst, GLib

    def status(self) -> dict:
        with self._lock:
            state = dict(self._state)

        last_frame = state.get("last_frame_at_unix")
        if (
            state["camera_status"] == "RUNNING"
            and last_frame is not None
            and time.time() - last_frame > self.frame_timeout_seconds
        ):
            state.update(
                camera_status="STALE",
                camera_error=(
                    "No decoded frame received for more than "
                    f"{self.frame_timeout_seconds:g} seconds"
                ),
            )
        return state

    def start(self) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()

            # Load lazily: telemetry-only installations do not need GStreamer
            # just to expose /health and /telemetry.
            self._load_gst()
            self._stop_event.clear()
            self._latest_jpeg = None
            self._preview_version = 0
            self._frame_times.clear()
            self._state = {
                **self._empty_state(),
                "camera_status": "STARTING",
                "expected_fps": self.expected_fps,
                "width": self.width,
                "height": self.height,
                "stream_port": self.port,
                "payload_type": self.payload_type,
                "decoder": self.decoder,
            }
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="jetson-camera-receiver",
            )
            self._thread.start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                self._state.update(camera_running=False, camera_status="STOPPED")
                return self.status()
            self._state["camera_status"] = "STOPPING"
            self._stop_event.set()
            loop = self._loop
            self._frame_ready.notify_all()

        if loop and loop.is_running():
            loop.quit()
        thread.join(timeout=12)
        if thread.is_alive():
            raise CameraStreamError("GStreamer camera receiver did not stop within 12 seconds")
        return self.status()

    def preview_stream(self) -> Iterator[bytes]:
        """Yield multipart JPEG chunks for an HTML ``img`` element."""

        if not self._thread or not self._thread.is_alive():
            self.start()

        last_version = -1
        while True:
            with self._frame_ready:
                self._frame_ready.wait_for(
                    lambda: self._preview_version != last_version
                    or self._state["camera_status"] in {"FAILED", "STOPPED"},
                    timeout=5,
                )
                jpeg = self._latest_jpeg
                version = self._preview_version
                status = self._state["camera_status"]

            if jpeg is not None and version != last_version:
                last_version = version
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode("ascii")
                    + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
            elif status in {"FAILED", "STOPPED"}:
                return

    def _run(self) -> None:
        restart_delay = 1.0
        while not self._stop_event.is_set():
            failure = self._run_once()
            if self._stop_event.is_set():
                break
            with self._frame_ready:
                self._state.update(
                    camera_running=False,
                    camera_status="DEGRADED",
                    camera_error=failure,
                )
                self._frame_ready.notify_all()
            self._stop_event.wait(restart_delay)
            restart_delay = min(10.0, restart_delay * 2)

        with self._frame_ready:
            self._pipeline = None
            self._loop = None
            self._thread = None
            self._state.update(camera_running=False, camera_status="STOPPED")
            self._frame_ready.notify_all()

    def _run_once(self) -> str:
        Gst, GLib = self._load_gst()
        self._gst = Gst
        failure = "GStreamer camera receiver stopped unexpectedly"
        pipeline = None
        try:
            pipeline = Gst.parse_launch(self.build_pipeline())
            sink = pipeline.get_by_name("jpeg_sink")
            if sink is None:
                raise CameraStreamError("receiver pipeline is missing jpeg_sink")

            sink.connect("new-sample", self._on_decoded_sample)
            loop = GLib.MainLoop()
            bus = pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_bus_message, loop)
            with self._lock:
                self._pipeline = pipeline
                self._loop = loop
                self._state.update(camera_running=True, camera_status="STARTING", camera_error=None)
            pipeline.set_state(Gst.State.PLAYING)
            loop.run()
            failure = self._state.get("camera_error") or failure
        except Exception as exc:  # Keep the telemetry backend alive on video errors.
            failure = str(exc)
        finally:
            if pipeline is not None:
                pipeline.set_state(Gst.State.NULL)
            with self._lock:
                self._pipeline = None
                self._loop = None
        return failure

    def _on_bus_message(self, _bus, message, loop) -> None:
        if message.type == self._gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            with self._lock:
                self._state["camera_error"] = str(error)
            loop.quit()
        elif message.type == self._gst.MessageType.EOS:
            loop.quit()

    def _on_decoded_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return self._gst.FlowReturn.ERROR
        buffer = sample.get_buffer()
        success, mapped = buffer.map(self._gst.MapFlags.READ)
        if not success:
            return self._gst.FlowReturn.OK
        try:
            self._publish_frame(bytes(mapped.data))
        finally:
            buffer.unmap(mapped)
        return self._gst.FlowReturn.OK

    def _publish_frame(self, jpeg: bytes) -> None:
        now = time.time()
        monotonic_now = time.monotonic()
        with self._frame_ready:
            self._state["camera_running"] = True
            self._state["camera_status"] = "RUNNING"
            self._state["camera_error"] = None
            self._state["frame_count"] += 1
            self._state["last_frame_at_unix"] = now
            self._state["last_frame_timestamp"] = datetime.now(timezone.utc).isoformat()
            self._frame_times.append(monotonic_now)
            if len(self._frame_times) >= 2 and self._frame_times[-1] > self._frame_times[0]:
                self._state["fps"] = (len(self._frame_times) - 1) / (
                    self._frame_times[-1] - self._frame_times[0]
                )
            self._latest_jpeg = jpeg
            self._preview_version += 1
            self._frame_ready.notify_all()
