from __future__ import annotations

import os
import ipaddress
import re
import signal
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Iterator


class JetsonVideoError(RuntimeError):
    """Raised when the GStreamer Jetson video receiver cannot be started."""


class JpegFrameParser:
    """Extract concatenated JPEG buffers from a byte stream."""

    def __init__(self, max_frame_bytes: int = 32 * 1024 * 1024):
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        if data:
            self._buffer.extend(data)

        frames: list[bytes] = []
        while True:
            start = self._buffer.find(b"\xff\xd8")
            if start < 0:
                # Keep a possible first byte of the next SOI marker.
                if self._buffer and self._buffer[-1] == 0xFF:
                    self._buffer[:] = self._buffer[-1:]
                else:
                    self._buffer.clear()
                break

            if start:
                del self._buffer[:start]

            end = self._buffer.find(b"\xff\xd9", 2)
            if end < 0:
                if len(self._buffer) > self.max_frame_bytes:
                    # A broken pipeline must not make the backend retain an
                    # unbounded amount of data while waiting for an EOI.
                    self._buffer.clear()
                break

            end += 2
            frames.append(bytes(self._buffer[:end]))
            del self._buffer[:end]

        return frames


class JetsonVideoService:
    """Receive Jetson H.264/RTP/UDP and fan out decoded JPEG frames.

    The GCS backend deliberately terminates the UDP stream. Browsers receive
    the resulting frames through ``preview_stream`` rather than accessing RTP
    directly. ``gst-launch-1.0`` is invoked without a shell so the pipeline
    arguments remain explicit and validated.
    """

    def __init__(
        self,
        frame_handler: Callable[[bytes, int, float, float, int, int, float], None] | None = None,
        error_handler: Callable[[str], None] | None = None,
    ):
        self.frame_handler = frame_handler
        self.error_handler = error_handler

        self.bind_address = os.getenv("JETSON_VIDEO_BIND_ADDRESS", "0.0.0.0")
        try:
            ipaddress.ip_address(self.bind_address)
        except ValueError as exc:
            raise JetsonVideoError("JETSON_VIDEO_BIND_ADDRESS must be a valid IP address") from exc
        self.port = self._env_int("JETSON_VIDEO_PORT", 5000, 1, 65535)
        self.payload_type = self._env_int("JETSON_VIDEO_PAYLOAD_TYPE", 96, 0, 127)
        self.jitter_latency_ms = self._env_int("JETSON_VIDEO_JITTER_LATENCY_MS", 80, 0, 5000)
        self.width = self._env_int("JETSON_VIDEO_PREVIEW_WIDTH", 1280, 16, 7680)
        self.height = self._env_int("JETSON_VIDEO_PREVIEW_HEIGHT", 720, 16, 4320)
        self.expected_fps = self._env_float("JETSON_VIDEO_FPS", 30.0, 0.1, 240.0)
        self.frame_timeout_seconds = self._env_float("JETSON_VIDEO_FRAME_TIMEOUT_SECONDS", 5.0, 0.5, 60.0)
        self.jpeg_quality = self._env_int("JETSON_VIDEO_PREVIEW_JPEG_QUALITY", 75, 1, 100)
        self.gst_binary = os.getenv("JETSON_VIDEO_GST_LAUNCH", "gst-launch-1.0")
        self.decoder = os.getenv("JETSON_VIDEO_DECODER", "avdec_h264").strip() or "avdec_h264"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.decoder):
            raise JetsonVideoError("JETSON_VIDEO_DECODER must be a single GStreamer element name")

        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._latest_jpeg: bytes | None = None
        self._preview_version = 0
        self._fps_samples: deque[float] = deque(maxlen=60)
        self._camera_state = self._empty_state()

    @staticmethod
    def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
        raw = os.getenv(name, str(default))
        try:
            value = int(raw)
        except ValueError as exc:
            raise JetsonVideoError(f"{name} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise JetsonVideoError(f"{name} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
        raw = os.getenv(name, str(default))
        try:
            value = float(raw)
        except ValueError as exc:
            raise JetsonVideoError(f"{name} must be a number") from exc
        if not minimum <= value <= maximum:
            raise JetsonVideoError(f"{name} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _empty_state() -> dict:
        return {
            "camera_source": "jetson_udp",
            "camera_running": False,
            "camera_status": "STOPPED",
            "camera_error": None,
            "camera_index": None,
            "width": None,
            "height": None,
            "fps": 0.0,
            "expected_fps": None,
            "frame_count": 0,
            "preview_frame_count": 0,
            "last_frame_timestamp": None,
            "last_frame_at_unix": None,
            "packet_error_count": 0,
            "decoder_error_count": 0,
            "last_pipeline_message": None,
            "pipeline_returncode": None,
            "stream_port": None,
            "payload_type": None,
            "decoder": None,
        }

    def status(self) -> dict:
        with self._lock:
            state = dict(self._camera_state)
        if (
            state["camera_status"] == "LIVE"
            and state["last_frame_at_unix"] is not None
            and time.time() - state["last_frame_at_unix"] > self.frame_timeout_seconds
        ):
            state["camera_status"] = "STALE"
            state["camera_error"] = (
                f"No decoded frame received for more than {self.frame_timeout_seconds:g} seconds"
            )
        return state

    def build_pipeline(self) -> list[str]:
        gst_path = shutil.which(self.gst_binary) or (
            self.gst_binary if os.path.isabs(self.gst_binary) else None
        )
        if not gst_path:
            raise JetsonVideoError(
                f"{self.gst_binary} was not found; install GStreamer and verify JETSON_VIDEO_GST_LAUNCH"
            )

        caps = (
            "application/x-rtp,media=video,clock-rate=90000,"
            f"encoding-name=H264,payload={self.payload_type}"
        )
        raw_caps = f"video/x-raw,format=I420,width={self.width},height={self.height}"
        return [
            gst_path,
            "-q",
            "udpsrc",
            f"address={self.bind_address}",
            f"port={self.port}",
            f"caps={caps}",
            "!",
            "rtpjitterbuffer",
            f"latency={self.jitter_latency_ms}",
            "drop-on-latency=true",
            "!",
            "rtph264depay",
            "!",
            "h264parse",
            "!",
            self.decoder,
            "!",
            "videoconvert",
            "!",
            "videoscale",
            "!",
            raw_caps,
            "!",
            "jpegenc",
            f"quality={self.jpeg_quality}",
            "!",
            "fdsink",
            "fd=1",
            "sync=false",
        ]

    def start(self) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()

            # Validate the executable and all configured values before
            # starting a background thread, so a bad configuration is visible
            # to the /camera/start request immediately.
            self.build_pipeline()
            self._stop_event.clear()
            self._latest_jpeg = None
            self._preview_version = 0
            self._fps_samples.clear()
            self._camera_state = {
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
                name="jetson-gstreamer-receiver",
            )
            self._thread.start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                self._camera_state.update(camera_running=False, camera_status="STOPPED")
                return self.status()
            self._camera_state["camera_status"] = "STOPPING"
            self._stop_event.set()
            process = self._process

        self._terminate_process(process)
        thread.join(timeout=10)
        if thread.is_alive():
            with self._lock:
                process = self._process
            self._terminate_process(process, force=True)
            thread.join(timeout=2)
        if thread.is_alive():
            raise JetsonVideoError("GStreamer video receiver did not stop within 12 seconds")
        return self.status()

    def preview_stream(self) -> Iterator[bytes]:
        self.start()
        with self._lock:
            last_version = self._preview_version - 1 if self._latest_jpeg is not None else self._preview_version

        while True:
            with self._frame_ready:
                self._frame_ready.wait_for(
                    lambda: self._preview_version != last_version
                    or self._camera_state["camera_status"] in {"FAILED", "STOPPED"},
                    timeout=5,
                )
                jpeg = self._latest_jpeg
                version = self._preview_version
                camera_status = self._camera_state["camera_status"]
            if jpeg is not None and version != last_version:
                last_version = version
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode("ascii")
                    + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
            elif camera_status in {"FAILED", "STOPPED"}:
                return

    def _run(self) -> None:
        process: subprocess.Popen[bytes] | None = None
        stderr_thread: threading.Thread | None = None
        parser = JpegFrameParser()
        received_frame = False
        failure: str | None = None

        try:
            command = self.build_pipeline()
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                start_new_session=os.name != "nt",
            )
            with self._lock:
                self._process = process
                self._camera_state["pipeline_pid"] = process.pid
                self._camera_state["camera_running"] = True

            stderr_thread = threading.Thread(
                target=self._read_pipeline_messages,
                args=(process.stderr,),
                daemon=True,
                name="jetson-gstreamer-stderr",
            )
            stderr_thread.start()

            assert process.stdout is not None
            read_chunk = getattr(process.stdout, "read1", process.stdout.read)
            while not self._stop_event.is_set():
                chunk = read_chunk(64 * 1024)
                if not chunk:
                    break
                for jpeg in parser.feed(chunk):
                    received_frame = True
                    self._publish_frame(jpeg)

            returncode = process.poll()
            if self._stop_event.is_set():
                return
            if returncode not in (None, 0):
                failure = self._pipeline_failure_message(returncode)
            elif not received_frame:
                failure = "GStreamer exited before receiving a decoded video frame"
            else:
                failure = "GStreamer video receiver exited unexpectedly"
        except FileNotFoundError as exc:
            failure = f"Cannot start GStreamer: {exc}"
        except Exception as exc:
            failure = str(exc)
        finally:
            if process is not None and process.poll() is None:
                self._terminate_process(process)
            if stderr_thread and stderr_thread.is_alive():
                stderr_thread.join(timeout=1)
            if process is not None:
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()

            with self._frame_ready:
                self._process = None
                self._thread = None
                self._camera_state["pipeline_pid"] = None
                self._camera_state["pipeline_returncode"] = process.poll() if process else None
                if self._stop_event.is_set():
                    self._camera_state.update(camera_running=False, camera_status="STOPPED")
                elif failure:
                    self._camera_state.update(
                        camera_running=False,
                        camera_status="FAILED",
                        camera_error=failure,
                    )
                else:
                    self._camera_state.update(camera_running=False, camera_status="STOPPED")
                self._frame_ready.notify_all()

            if failure and not self._stop_event.is_set() and self.error_handler:
                self.error_handler(failure)

    def _publish_frame(self, jpeg: bytes) -> None:
        now = time.time()
        monotonic_now = time.monotonic()
        with self._frame_ready:
            frame_id = self._camera_state["frame_count"]
            self._camera_state["frame_count"] += 1
            self._camera_state["preview_frame_count"] += 1
            self._camera_state["last_frame_at_unix"] = now
            self._camera_state["last_frame_timestamp"] = datetime.fromtimestamp(
                now, timezone.utc
            ).isoformat()
            self._fps_samples.append(monotonic_now)
            if len(self._fps_samples) >= 2:
                elapsed = self._fps_samples[-1] - self._fps_samples[0]
                if elapsed > 0:
                    self._camera_state["fps"] = (len(self._fps_samples) - 1) / elapsed
            if self._camera_state["camera_status"] == "STARTING":
                self._camera_state["camera_status"] = "LIVE"
            self._latest_jpeg = jpeg
            self._preview_version += 1
            self._frame_ready.notify_all()

        if self.frame_handler:
            self.frame_handler(
                jpeg,
                frame_id,
                now,
                monotonic_now,
                self.width,
                self.height,
                float(self.status().get("fps") or self.expected_fps),
            )

    def _read_pipeline_messages(self, stream) -> None:
        if stream is None:
            return
        for raw_line in iter(stream.readline, b""):
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            lowered = line.lower()
            with self._lock:
                self._camera_state["last_pipeline_message"] = line[-1000:]
                if any(token in lowered for token in ("error", "warning", "failed")):
                    if any(token in lowered for token in ("udp", "rtp", "packet", "jitter", "depay")):
                        self._camera_state["packet_error_count"] += 1
                    if any(token in lowered for token in ("h264", "decoder", "decode", "avdec")):
                        self._camera_state["decoder_error_count"] += 1

    def _pipeline_failure_message(self, returncode: int) -> str:
        with self._lock:
            message = self._camera_state.get("last_pipeline_message")
        if message:
            return f"GStreamer exited with code {returncode}: {message}"
        return f"GStreamer exited with code {returncode}"

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes] | None, force: bool = False) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            if os.name != "nt" and process.pid:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            else:
                if force:
                    process.kill()
                else:
                    process.terminate()
            process.wait(timeout=2)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            if not force and process.poll() is None:
                try:
                    if os.name != "nt" and process.pid:
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=2)
                except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
                    pass
