"""Frame-aware PyGObject receiver for Jetson H.264/RTP/UDP preview."""

from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Callable, Iterator

from .frame_sync import FrameSyncError, FrameSynchronizer, RtpIdentityTracker, StreamRegistry
from .latency_metrics import LatencyMetrics


class JetsonVideoError(RuntimeError):
    pass


class JpegFrameParser:
    """Retained only for diagnostic byte-stream tooling; production uses appsink."""

    def __init__(self, max_frame_bytes: int = 32 * 1024 * 1024):
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        if data:
            self._buffer.extend(data)
        frames = []
        while True:
            start = self._buffer.find(b"\xff\xd8")
            if start < 0:
                self._buffer[:] = self._buffer[-1:] if self._buffer and self._buffer[-1] == 0xFF else b""
                break
            if start:
                del self._buffer[:start]
            end = self._buffer.find(b"\xff\xd9", 2)
            if end < 0:
                if len(self._buffer) > self.max_frame_bytes:
                    self._buffer.clear()
                break
            end += 2
            frames.append(bytes(self._buffer[:end]))
            del self._buffer[:end]
        return frames


class JetsonVideoService:
    """Parse RTP identity before decoding and publish only exact synchronized frames."""

    def __init__(
        self,
        frame_handler: Callable[[bytes, int, float, float, int, int, float], None] | None = None,
        error_handler: Callable[[str], None] | None = None,
        stream_registry: StreamRegistry | None = None,
        synchronizer: FrameSynchronizer | None = None,
    ):
        self.frame_handler = frame_handler
        self.error_handler = error_handler
        self.stream_registry = stream_registry or StreamRegistry()
        self.synchronizer = synchronizer or FrameSynchronizer()
        self.identity_tracker = RtpIdentityTracker(self.stream_registry)
        self.bind_address = os.getenv("JETSON_VIDEO_BIND_ADDRESS", "0.0.0.0")
        try:
            ipaddress.ip_address(self.bind_address)
        except ValueError as exc:
            raise JetsonVideoError("JETSON_VIDEO_BIND_ADDRESS must be a valid IP address") from exc
        self.port = self._env_int("JETSON_VIDEO_PORT", 5000, 1, 65535)
        self.payload_type = self._env_int("JETSON_VIDEO_PAYLOAD_TYPE", 96, 0, 127)
        self.jitter_latency_ms = self._env_int("JETSON_VIDEO_JITTER_LATENCY_MS", 80, 0, 5000)
        self.width = self._env_int("JETSON_VIDEO_PREVIEW_WIDTH", 960, 16, 7680)
        self.height = self._env_int("JETSON_VIDEO_PREVIEW_HEIGHT", 540, 16, 4320)
        self.expected_fps = self._env_float("JETSON_VIDEO_FPS", 15.0, 0.1, 240.0)
        self.frame_timeout_seconds = self._env_float("JETSON_VIDEO_FRAME_TIMEOUT_SECONDS", 5.0, 0.5, 60.0)
        self.jpeg_quality = self._env_int("JETSON_VIDEO_PREVIEW_JPEG_QUALITY", 75, 1, 100)
        self.decoder = os.getenv("JETSON_VIDEO_DECODER", "avdec_h264").strip() or "avdec_h264"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.decoder):
            raise JetsonVideoError("JETSON_VIDEO_DECODER must be one GStreamer element name")
        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pipeline = None
        self._loop = None
        self._gst = None
        self._latest_jpeg: bytes | None = None
        self._latest_matched = None
        self._preview_version = 0
        self._fps_samples: deque[float] = deque(maxlen=60)
        self._decode_publish_latency = LatencyMetrics()
        self._identity_by_pts: OrderedDict[int, tuple[object, int]] = OrderedDict()
        self._camera_state = self._empty_state()

    @staticmethod
    def _env_int(name, default, minimum, maximum):
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError as exc:
            raise JetsonVideoError(f"{name} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise JetsonVideoError(f"{name} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _env_float(name, default, minimum, maximum):
        try:
            value = float(os.getenv(name, str(default)))
        except ValueError as exc:
            raise JetsonVideoError(f"{name} must be a number") from exc
        if not minimum <= value <= maximum:
            raise JetsonVideoError(f"{name} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _empty_state():
        return {
            "camera_source": "jetson_udp", "camera_running": False, "camera_status": "STOPPED",
            "camera_error": None, "width": None, "height": None, "fps": 0.0,
            "expected_fps": None, "frame_count": 0, "preview_frame_count": 0,
            "last_frame_timestamp": None, "last_frame_at_unix": None,
            "packet_error_count": 0, "decoder_error_count": 0,
            "identity_error_count": 0, "metadata_timeout_count": 0,
            "restart_count": 0, "stream_port": None, "payload_type": None,
            "decoder": None, "stream_registration": None,
            "latency": {"decode_to_ground_publish": LatencyMetrics().snapshot()},
        }

    def build_pipeline(self) -> str:
        caps = f"application/x-rtp,media=video,clock-rate=90000,encoding-name=H264,payload={self.payload_type}"
        return (
            f'udpsrc name=rtp_source address="{self.bind_address}" port={self.port} caps="{caps}" ! '
            f'rtpjitterbuffer name=rtp_jitter latency={self.jitter_latency_ms} drop-on-latency=true ! '
            f'rtph264depay ! h264parse ! {self.decoder} ! videoconvert ! videoscale ! '
            f'video/x-raw,format=I420,width={self.width},height={self.height} ! '
            f'jpegenc quality={self.jpeg_quality} ! '
            'appsink name=jpeg_sink emit-signals=true max-buffers=4 drop=true sync=false'
        )

    @staticmethod
    def _load_gst():
        try:
            import gi
            gi.require_version("Gst", "1.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import GLib, Gst
        except ImportError as exc:
            raise JetsonVideoError("PyGObject with GStreamer 1.0 is required for the frame-aware receiver") from exc
        Gst.init([])
        return Gst, GLib

    def status(self):
        with self._lock:
            state = dict(self._camera_state)
        state["stream_registration"] = self.stream_registry.latest()
        state["latency"] = {
            "decode_to_ground_publish": self._decode_publish_latency.snapshot(),
        }
        if state["camera_status"] == "RUNNING" and state["last_frame_at_unix"] is not None and time.time() - state["last_frame_at_unix"] > self.frame_timeout_seconds:
            state.update(camera_status="STALE", camera_error=f"No decoded frame received for more than {self.frame_timeout_seconds:g} seconds")
        return state

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._load_gst()
            self._stop_event.clear()
            self._latest_jpeg = None
            self._preview_version = 0
            self._fps_samples.clear()
            self._decode_publish_latency.clear()
            self._camera_state = {
                **self._empty_state(), "camera_status": "STARTING", "expected_fps": self.expected_fps,
                "width": self.width, "height": self.height, "stream_port": self.port,
                "payload_type": self.payload_type, "decoder": self.decoder,
            }
            self._thread = threading.Thread(target=self._run, daemon=True, name="jetson-pygobject-receiver")
            self._thread.start()
        return self.status()

    def stop(self):
        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                self._camera_state.update(camera_running=False, camera_status="STOPPED")
                return self.status()
            self._camera_state["camera_status"] = "STOPPING"
            self._stop_event.set()
            loop = self._loop
        if loop and loop.is_running():
            loop.quit()
        thread.join(timeout=12)
        if thread.is_alive():
            raise JetsonVideoError("GStreamer video receiver did not stop within 12 seconds")
        return self.status()

    def reset_stream(self):
        self.identity_tracker.reset()
        self.synchronizer.reset()
        with self._frame_ready:
            self._identity_by_pts.clear()
            self._latest_jpeg = None
            self._latest_matched = None
            self._camera_state["frame_count"] = 0
            self._frame_ready.notify_all()

    def ingest_metadata(self, payload: dict) -> bool:
        accepted = self.synchronizer.push_metadata(payload)
        self._drain_ready()
        return accepted

    def wait_for_vision_frame(self, last_version: int, timeout: float = 5.0):
        with self._frame_ready:
            self._frame_ready.wait_for(
                lambda: self._preview_version != last_version
                or self._camera_state["camera_status"] in {"FAILED", "STOPPED"},
                timeout=timeout,
            )
            return self._preview_version, self._latest_matched, self.status()

    def preview_stream(self) -> Iterator[bytes]:
        self.start()
        last_version = -1
        while True:
            with self._frame_ready:
                self._frame_ready.wait_for(lambda: self._preview_version != last_version or self._camera_state["camera_status"] in {"FAILED", "STOPPED"}, timeout=5)
                jpeg, version, status = self._latest_jpeg, self._preview_version, self._camera_state["camera_status"]
            if jpeg is not None and version != last_version:
                last_version = version
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode("ascii") + b"\r\n\r\n" + jpeg + b"\r\n"
            elif status in {"FAILED", "STOPPED"}:
                return

    def _run(self):
        restart_delay = 1.0
        while not self._stop_event.is_set():
            failure = self._run_once()
            if self._stop_event.is_set():
                break
            with self._frame_ready:
                self._camera_state.update(camera_running=False, camera_status="DEGRADED", camera_error=failure, restart_count=self._camera_state["restart_count"] + 1)
                self._frame_ready.notify_all()
            self._stop_event.wait(restart_delay)
            restart_delay = min(10.0, restart_delay * 2)
        with self._frame_ready:
            self._pipeline = None
            self._loop = None
            self._thread = None
            self._camera_state.update(camera_running=False, camera_status="STOPPED")
            self._frame_ready.notify_all()

    def _run_once(self):
        Gst, GLib = self._load_gst()
        self._gst = Gst
        failure = "GStreamer receiver stopped unexpectedly"
        try:
            pipeline = Gst.parse_launch(self.build_pipeline())
            jitter = pipeline.get_by_name("rtp_jitter")
            sink = pipeline.get_by_name("jpeg_sink")
            if jitter is None or sink is None:
                raise JetsonVideoError("receiver pipeline is missing named identity/decode elements")
            jitter.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._on_rtp_probe)
            sink.connect("new-sample", self._on_decoded_sample)
            loop = GLib.MainLoop()
            bus = pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_bus_message, loop)
            GLib.timeout_add(20, self._on_sync_tick)
            with self._lock:
                self._pipeline, self._loop = pipeline, loop
                self._camera_state.update(camera_running=True, camera_status="STARTING", camera_error=None)
            pipeline.set_state(Gst.State.PLAYING)
            loop.run()
            failure = self._camera_state.get("camera_error") or failure
        except Exception as exc:
            failure = str(exc)
        finally:
            if self._pipeline is not None:
                self._pipeline.set_state(Gst.State.NULL)
            with self._lock:
                self._pipeline = None
                self._loop = None
        return failure

    def _on_bus_message(self, _bus, message, loop):
        if message.type == self._gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            with self._lock:
                self._camera_state["camera_error"] = str(error)
                self._camera_state["decoder_error_count"] += 1
            loop.quit()
        elif message.type == self._gst.MessageType.EOS:
            loop.quit()

    def _on_rtp_probe(self, _pad, info):
        buffer = info.get_buffer()
        if buffer is None:
            return self._gst.PadProbeReturn.OK
        success, mapped = buffer.map(self._gst.MapFlags.READ)
        if not success:
            return self._gst.PadProbeReturn.OK
        try:
            observed = self.identity_tracker.observe(bytes(mapped.data))
            if observed is not None and buffer.pts != self._gst.CLOCK_TIME_NONE:
                key, rtp_timestamp, _extended = observed
                with self._lock:
                    self._identity_by_pts[int(buffer.pts)] = (key, rtp_timestamp)
                    while len(self._identity_by_pts) > 512:
                        self._identity_by_pts.popitem(last=False)
        except FrameSyncError:
            with self._lock:
                self._camera_state["identity_error_count"] += 1
        finally:
            buffer.unmap(mapped)
        return self._gst.PadProbeReturn.OK

    def _on_decoded_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return self._gst.FlowReturn.ERROR
        buffer = sample.get_buffer()
        success, mapped = buffer.map(self._gst.MapFlags.READ)
        if not success:
            return self._gst.FlowReturn.OK
        try:
            with self._lock:
                identity = self._identity_by_pts.get(int(buffer.pts)) if buffer.pts != self._gst.CLOCK_TIME_NONE else None
            if identity is None:
                with self._lock:
                    self._camera_state["identity_error_count"] += 1
                return self._gst.FlowReturn.OK
            key, rtp_timestamp = identity
            self.synchronizer.push_video(key, bytes(mapped.data), rtp_timestamp)
            self._drain_ready()
        finally:
            buffer.unmap(mapped)
        return self._gst.FlowReturn.OK

    def _on_sync_tick(self):
        self._drain_ready()
        return bool(self._loop and self._loop.is_running() and not self._stop_event.is_set())

    def _drain_ready(self):
        for frame in self.synchronizer.pop_ready():
            self._publish_frame(frame)

    def _publish_frame(self, frame):
        now = time.time()
        monotonic_now = time.monotonic()
        with self._frame_ready:
            self._camera_state["frame_count"] += 1
            self._camera_state["preview_frame_count"] += 1
            self._camera_state["last_frame_at_unix"] = now
            self._camera_state["last_frame_timestamp"] = datetime.now(timezone.utc).isoformat()
            if frame.state == "METADATA_TIMEOUT":
                self._camera_state["metadata_timeout_count"] += 1
            self._fps_samples.append(monotonic_now)
            if len(self._fps_samples) >= 2 and self._fps_samples[-1] > self._fps_samples[0]:
                self._camera_state["fps"] = (len(self._fps_samples) - 1) / (self._fps_samples[-1] - self._fps_samples[0])
            self._camera_state.update(camera_status="RUNNING", camera_error=None)
            self._latest_jpeg = frame.jpeg
            self._latest_matched = frame
            self._preview_version += 1
            self._decode_publish_latency.observe(
                max(0, time.monotonic_ns() - frame.decoded_monotonic_ns) / 1_000_000
            )
            self._frame_ready.notify_all()
        if self.frame_handler:
            self.frame_handler(frame.jpeg, frame.key.frame_id, now, monotonic_now, self.width, self.height, float(self.status().get("fps") or self.expected_fps))
