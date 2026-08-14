from __future__ import annotations

import json
import os
import platform
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from .jetson_video_service import JetsonVideoError, JetsonVideoService
from .jetson_recording_client import JetsonRecordingClient, JetsonRecordingError
from .frame_sync import FrameSynchronizer, StreamRegistry
from .coordinate_estimator import CameraCalibration, estimate_target_latlon
from .live_detections import LiveDetectionStore
from .telemetry_recorder import DEFAULT_JOIN_WINDOW_SECONDS


class FlightRecorderError(RuntimeError):
    pass


class FlightRecorder:
    """Own one camera source for preview and recording control.

    ``CAMERA_SOURCE=jetson_udp`` receives the Arducam stream at the GCS via
    GStreamer, while recording commands are proxied to the Jetson agent. The
    GCS does not create a relay video for this source. The v0.3 release rejects
    every non-Arducam source.
    """

    def __init__(
        self,
        telemetry_provider: Callable[[], dict],
        recordings_dir: str | Path | None = None,
        stream_registry: StreamRegistry | None = None,
        synchronizer: FrameSynchronizer | None = None,
        telemetry_history: Callable[[float, float], dict | None] | None = None,
        telemetry_session_start: Callable[[Path], None] | None = None,
        telemetry_session_stop: Callable[[], None] | None = None,
    ):
        self.telemetry_provider = telemetry_provider
        # Per-session ground telemetry.jsonl (Task #12): bound to
        # TelemetryRecorder.start_session/end_session. Best-effort -- a
        # failure here must never block or unwind an actual recording
        # start/stop, since the Jetson is the authoritative recorder.
        self.telemetry_session_start = telemetry_session_start
        self.telemetry_session_stop = telemetry_session_stop
        # Ground-side target geolocation: telemetry_history looks up the
        # vehicle pose nearest a detection's capture time (see
        # telemetry_recorder.TelemetryRecorder.nearest); camera_calibration
        # holds the intrinsics/mount used to turn a bbox into a ray. See
        # coordinate_estimator's module docstring for the calibration caveat
        # -- estimates are tagged ESTIMATED_UNCALIBRATED until that's fixed.
        self.telemetry_history = telemetry_history
        self.camera_calibration = CameraCalibration()
        self.live_detections = LiveDetectionStore()
        self.recordings_dir = Path(
            recordings_dir or os.getenv("FLIGHT_RECORDINGS_DIR") or Path.cwd() / "recordings"
        ).resolve()

        source = os.getenv("CAMERA_SOURCE", os.getenv("VIDEO_SOURCE", "jetson_udp"))
        source = source.strip().lower()
        self.camera_source = {
            "jetson": "jetson_udp",
            "udp": "jetson_udp",
            "gstreamer": "jetson_udp",
        }.get(source, source)
        if self.camera_source != "jetson_udp":
            raise FlightRecorderError(
                f"Unsupported CAMERA_SOURCE={source!r}; v0.3 only permits jetson_udp Arducam"
            )

        # Legacy EasyCAP settings. They are intentionally not used by the
        # Jetson UDP path.
        self.camera_index = int(os.getenv("VRX_CAMERA_INDEX", "0"))
        self.requested_width = int(os.getenv("VRX_CAPTURE_WIDTH", "640"))
        self.requested_height = int(os.getenv("VRX_CAPTURE_HEIGHT", "480"))
        self.requested_fps = float(os.getenv("VRX_CAPTURE_FPS", "25"))
        self.video_standard = os.getenv("VRX_VIDEO_STANDARD", "PAL")
        self.codec = os.getenv("VRX_VIDEO_CODEC", "mp4v")
        self.jpeg_quality = int(os.getenv("VRX_PREVIEW_JPEG_QUALITY", "75"))

        self._lock = threading.RLock()
        self._record_lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._camera_stop = threading.Event()
        self._camera_thread: threading.Thread | None = None
        self._latest_jpeg: bytes | None = None
        self._preview_version = 0
        self._camera_state = self._empty_camera_state()
        self._state = self._idle_recording_state()

        # These resources are created and used by the frame/capture thread.
        self._writer = None
        self._telemetry_file = None
        self._recording_monotonic_start: float | None = None
        self._capture_actual: dict = {}

        self._jetson_video: JetsonVideoService | None = None
        self._jetson_recording: JetsonRecordingClient | None = None
        if self.camera_source == "jetson_udp":
            try:
                self._jetson_recording = JetsonRecordingClient()
                self._jetson_video = JetsonVideoService(
                    frame_handler=self._handle_jetson_frame,
                    error_handler=self._handle_jetson_error,
                    stream_registry=stream_registry,
                    synchronizer=synchronizer,
                )
                autostart = os.getenv("JETSON_VIDEO_AUTOSTART", "true").strip().lower()
                if autostart in {"1", "true", "yes", "on"} and self._jetson_recording.configured:
                    try:
                        # Keep the UDP socket/receiver ready independently of
                        # whether a browser currently has the MJPEG preview
                        # open. The receiver reconnects on its own.
                        self._jetson_video.start()
                    except JetsonVideoError as exc:
                        # A missing local GStreamer binary should be visible in
                        # status but must not prevent the backend from serving
                        # the recording-control API.
                        self._camera_state["camera_status"] = "FAILED"
                        self._camera_state["camera_error"] = str(exc)
            except (JetsonVideoError, JetsonRecordingError) as exc:
                raise FlightRecorderError(str(exc)) from exc

    @staticmethod
    def _empty_camera_state() -> dict:
        return {
            "camera_source": "easycap",
            "camera_running": False,
            "camera_status": "STOPPED",
            "camera_error": None,
            "camera_index": None,
            "width": None,
            "height": None,
            "fps": None,
            "frame_count": 0,
            "preview_frame_count": 0,
            "last_frame_timestamp": None,
            "last_frame_at_unix": None,
            "packet_error_count": 0,
            "decoder_error_count": 0,
            "last_pipeline_message": None,
        }

    @staticmethod
    def _idle_recording_state() -> dict:
        return {
            "recording": False,
            "status": "IDLE",
            "session_id": None,
            "session_dir": None,
            "started_at": None,
            "ended_at": None,
            "frame_count": 0,
            "error": None,
            "label": None,
        }

    def status(self) -> dict:
        if self._jetson_video is not None:
            camera_state = self._jetson_video.status()
        else:
            with self._lock:
                camera_state = dict(self._camera_state)
        if self._jetson_recording is not None:
            recording_state = self._jetson_recording.status()
        else:
            with self._lock:
                recording_state = dict(self._state)
        with self._lock:
            state = {**self._state, **recording_state, **camera_state}
        if state["recording"] and state["started_at"]:
            state["duration_seconds"] = max(0, time.time() - state["started_at"])
        else:
            start, end = state.get("started_at"), state.get("ended_at")
            state["duration_seconds"] = max(0, end - start) if start and end else 0
        return state

    def register_stream(self, payload: dict) -> dict:
        if self._jetson_video is None:
            raise FlightRecorderError("Jetson receiver is unavailable")
        previous = self._jetson_video.stream_registry.latest()
        registration = self._jetson_video.stream_registry.register(payload)
        identity_fields = ("mission_id", "capture_epoch", "camera_id", "ssrc")
        if previous is None or any(previous.get(field) != registration.get(field) for field in identity_fields):
            self._jetson_video.reset_stream()
        return registration

    def ingest_frame_metadata(self, payload: dict) -> bool:
        if self._jetson_video is None:
            raise FlightRecorderError("Jetson receiver is unavailable")
        self._attach_ground_coordinates(payload)
        self._record_live_detections(payload)
        return self._jetson_video.ingest_metadata(payload)

    def _record_live_detections(self, payload: dict) -> None:
        detections = payload.get("detections")
        if not detections:
            return
        snapshot = self.telemetry_provider() or {}
        vehicle = snapshot.get("telemetry") or {}
        fallback_lat = fallback_lon = None
        if snapshot.get("gps_valid"):
            fallback_lat, fallback_lon = vehicle.get("lat"), vehicle.get("lng")
        self.live_detections.add_many(
            detections,
            capture_utc_ns=payload.get("capture_utc_ns"),
            fallback_lat=fallback_lat,
            fallback_lon=fallback_lon,
        )

    def _attach_ground_coordinates(self, payload: dict) -> None:
        """Overwrite each detection's "coordinate" stub with a ground-side
        estimate, using telemetry buffered near this frame's capture time
        (see class docstring / coordinate_estimator for the method and its
        calibration caveat). Leaves "not_available" if no telemetry is
        available within the join window -- never raises.
        """
        detections = payload.get("detections")
        if not detections or self.telemetry_history is None:
            return
        capture_utc_ns = payload.get("capture_utc_ns")
        width, height = payload.get("source_width"), payload.get("source_height")
        if capture_utc_ns is None or not width or not height:
            return
        telemetry = self.telemetry_history(capture_utc_ns / 1e9, DEFAULT_JOIN_WINDOW_SECONDS)
        for detection in detections:
            bbox = detection.get("bbox_normalized_xyxy")
            if not bbox:
                continue
            detection["coordinate"] = estimate_target_latlon(
                bbox_normalized_xyxy=bbox,
                image_width=width,
                image_height=height,
                telemetry=telemetry,
                calibration=self.camera_calibration,
            )

    @property
    def vision_service(self) -> JetsonVideoService:
        if self._jetson_video is None:
            raise FlightRecorderError("Jetson receiver is unavailable")
        return self._jetson_video

    def start_camera(self) -> dict:
        if self._jetson_video is not None:
            try:
                self._jetson_video.start()
            except JetsonVideoError as exc:
                self._handle_camera_error(str(exc))
                raise FlightRecorderError(str(exc)) from exc
            return self.status()

        with self._lock:
            if self._camera_thread and self._camera_thread.is_alive():
                return self.status()
            self._camera_stop.clear()
            self._latest_jpeg = None
            self._preview_version = 0
            self._camera_state = {
                **self._empty_camera_state(),
                "camera_source": "easycap",
                "camera_status": "STARTING",
                "camera_index": self.camera_index,
            }
            self._camera_thread = threading.Thread(
                target=self._capture_loop,
                daemon=True,
                name="vrx-easycap-capture",
            )
            self._camera_thread.start()
        return self.status()

    def stop_camera(self) -> dict:
        current = self.status()
        if current.get("recording") is True or current.get("status") == "REMOTE_UNKNOWN":
            raise FlightRecorderError("Stop and save the active recording before stopping the camera")

        if self._jetson_video is not None:
            try:
                self._jetson_video.stop()
            except JetsonVideoError as exc:
                raise FlightRecorderError(str(exc)) from exc
            return self.status()

        with self._lock:
            thread = self._camera_thread
            if not thread or not thread.is_alive():
                self._camera_state.update(camera_running=False, camera_status="STOPPED")
                return self.status()
            self._camera_state["camera_status"] = "STOPPING"
            self._camera_stop.set()
        thread.join(timeout=10)
        if thread.is_alive():
            raise FlightRecorderError("Camera did not stop within 10 seconds")
        return self.status()

    def preview_stream(self) -> Iterator[bytes]:
        if self._jetson_video is not None:
            yield from self._jetson_video.preview_stream()
            return

        self.start_camera()
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

    def start(self, label: str | None = None, mission_id: str | None = None) -> dict:
        if self._jetson_recording is not None:
            return self._start_jetson_recording(label, mission_id)

        with self._lock:
            if self._state["recording"]:
                raise FlightRecorderError("A flight recording is already active")
            now = datetime.now(timezone.utc)
            session_id = f"flight-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
            session_dir = self.recordings_dir / session_id
            session_dir.mkdir(parents=True, exist_ok=False)
            self._state = {
                **self._idle_recording_state(),
                "recording": True,
                "status": "STARTING",
                "session_id": session_id,
                "session_dir": str(session_dir),
                "started_at": now.timestamp(),
                "label": (label or "").strip() or None,
            }
            self._write_metadata(session_dir / "metadata.json")
        try:
            self.start_camera()
        except FlightRecorderError as exc:
            self._finish_recording(str(exc))
            raise
        return self.status()

    def stop(self) -> dict:
        if self._jetson_recording is not None:
            current = self.status()
            if not current.get("recording"):
                raise FlightRecorderError("No high-res Jetson recording is active")
            try:
                self._jetson_recording.stop()
            except JetsonRecordingError as exc:
                raise FlightRecorderError(str(exc)) from exc
            self._end_telemetry_session()
            self.live_detections.reset()
            return self.status()

    def set_preview_source(self, source: str) -> dict:
        if self._jetson_recording is None:
            raise FlightRecorderError("preview source selection requires JETSON_RECORDING_AGENT_URL")
        try:
            return self._jetson_recording.set_preview_source(source)
        except JetsonRecordingError as exc:
            raise FlightRecorderError(str(exc)) from exc

        with self._frame_ready:
            if not self._state["recording"]:
                raise FlightRecorderError("No flight recording is active")
            self._state["status"] = "STOPPING"
            completed = self._frame_ready.wait_for(lambda: not self._state["recording"], timeout=10)
        if not completed:
            # A stopped/stalled stream may not produce another callback. Close
            # the writer from the request thread after the bounded wait rather
            # than leaving a recording permanently in STARTING/STOPPING.
            with self._lock:
                stop_error = (
                    "Recording stopped before receiving a video frame"
                    if self._state["frame_count"] == 0
                    else None
                )
            self._finish_recording(stop_error)
        return self.status()

    def _start_jetson_recording(self, label: str | None = None, mission_id: str | None = None) -> dict:
        current = self.status()
        if current.get("status") == "REMOTE_UNKNOWN":
            raise FlightRecorderError(
                "Jetson recording state is unknown; reconnect to Jetson before starting another session"
            )
        if current.get("recording") is True:
            raise FlightRecorderError("A high-res Jetson recording is already active")
        try:
            # Keep the GCS receiver ready before asking Jetson to send frames.
            self.start_camera()
            result = self._jetson_recording.start(
                label, video_port=self._jetson_video.port, mission_id=mission_id
            )
        except (FlightRecorderError, JetsonRecordingError) as exc:
            raise FlightRecorderError(str(exc)) from exc
        self.live_detections.reset()
        self._begin_telemetry_session(result.get("session_id"))
        return self.status()

    def _begin_telemetry_session(self, session_id: str | None) -> None:
        """Start mirroring ground Mission Planner telemetry into
        <recordings_dir>/<session_id>/telemetry.jsonl for the duration of this
        Jetson-proxied recording. session_id is shared with the Jetson's own
        session directory (its /recording/start response), so the two
        telemetry.jsonl files -- Jetson-onboard and ground/Mission-Planner --
        can be correlated post-flight by session_id even though they live on
        different machines. Best-effort: never raises, since the Jetson video
        recording this accompanies is the one that actually matters.
        """
        if not session_id or self.telemetry_session_start is None:
            return
        try:
            session_dir = self.recordings_dir / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            self.telemetry_session_start(session_dir)
        except OSError as exc:
            print(f"[FlightRecorder] Failed to start ground telemetry session log: {exc}")

    def _end_telemetry_session(self) -> None:
        if self.telemetry_session_stop is None:
            return
        try:
            self.telemetry_session_stop()
        except OSError as exc:
            print(f"[FlightRecorder] Failed to close ground telemetry session log: {exc}")

    def _write_metadata(self, path: Path):
        state = self.status()
        if self.camera_source == "jetson_udp":
            capture = {
                "device": "Arducam IMX477/B0249 via Jetson H.264/RTP/UDP",
                "source": "jetson_udp",
                "stream_port": state.get("stream_port"),
                "payload_type": state.get("payload_type"),
                "requested_width": state.get("width"),
                "requested_height": state.get("height"),
                "requested_fps": state.get("expected_fps"),
                "decoder": state.get("decoder"),
                "codec": self.codec,
                **self._capture_actual,
            }
        else:
            capture = {
                "device": "VRX RD945 via EasyCAP",
                "source": "easycap",
                "camera_index": self.camera_index,
                "requested_width": self.requested_width,
                "requested_height": self.requested_height,
                "requested_fps": self.requested_fps,
                "video_standard": self.video_standard,
                "codec": self.codec,
                **self._capture_actual,
            }
        metadata = {
            "schema_version": "2.0",
            "session_id": state["session_id"],
            "label": state.get("label"),
            "status": state["status"],
            "started_at_unix": state["started_at"],
            "started_at_iso": datetime.fromtimestamp(state["started_at"], timezone.utc).isoformat()
            if state["started_at"]
            else None,
            "ended_at_unix": state["ended_at"],
            "ended_at_iso": datetime.fromtimestamp(state["ended_at"], timezone.utc).isoformat()
            if state["ended_at"]
            else None,
            "frame_count": state["frame_count"],
            "duration_seconds": state["duration_seconds"],
            "synchronization": {
                "key": "frame_id",
                "description": "Each telemetry.jsonl row describes the matching encoded video frame in video.mp4.",
                "timestamps": ["captured_at_unix", "elapsed_monotonic_seconds"],
                "source_frame_id": "GCS decoded-frame sequence for Jetson UDP input",
            },
            "files": {"video": "video.mp4", "telemetry": "telemetry.jsonl", "metadata": "metadata.json"},
            "capture": capture,
            "host": {"system": platform.system(), "release": platform.release()},
            "error": state["error"],
        }
        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(path)

    def _begin_recording(self, cv2, width: int, height: int, fps: float):
        with self._record_lock:
            if self._writer is not None:
                return
            session_dir = Path(self._state["session_dir"])
            self._writer = cv2.VideoWriter(
                str(session_dir / "video.mp4"),
                cv2.VideoWriter_fourcc(*self.codec),
                fps,
                (width, height),
            )
            if not self._writer.isOpened():
                self._writer.release()
                self._writer = None
                raise FlightRecorderError(f"Cannot create video.mp4 with codec {self.codec}")
            self._telemetry_file = (session_dir / "telemetry.jsonl").open(
                "a", encoding="utf-8", buffering=1
            )
            self._recording_monotonic_start = time.monotonic()
            self._capture_actual.update(actual_width=width, actual_height=height, actual_fps=fps)
            with self._lock:
                self._state["status"] = "RECORDING"
            self._write_metadata(session_dir / "metadata.json")

    def _record_frame(self, frame, captured_at: float, source_frame_id: int | None = None):
        with self._record_lock:
            if self._writer is None or self._telemetry_file is None:
                return
            self._writer.write(frame)
            with self._lock:
                frame_id = self._state["frame_count"]
                self._state["frame_count"] += 1
            snapshot = self.telemetry_provider()
            row = {
                "frame_id": frame_id,
                "source_frame_id": source_frame_id,
                "captured_at_unix": captured_at,
                "elapsed_monotonic_seconds": time.monotonic() - self._recording_monotonic_start,
                "telemetry_version": snapshot.get("version"),
                "telemetry_received_at_unix": snapshot.get("timestamp"),
                "telemetry_stale": snapshot.get("stale"),
                "gps_valid": snapshot.get("gps_valid"),
                "telemetry": snapshot.get("telemetry", snapshot),
            }
            self._telemetry_file.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _finish_recording(self, error: str | None = None):
        with self._record_lock:
            with self._lock:
                if not self._state["recording"]:
                    return
                session_dir = self._state.get("session_dir")
            if self._writer is not None:
                self._writer.release()
                self._writer = None
            if self._telemetry_file is not None:
                self._telemetry_file.close()
                self._telemetry_file = None
            with self._frame_ready:
                self._state.update(
                    recording=False,
                    status="FAILED" if error else "COMPLETED",
                    ended_at=time.time(),
                    error=error,
                )
                self._frame_ready.notify_all()
            if session_dir:
                self._write_metadata(Path(session_dir) / "metadata.json")

    def _handle_jetson_frame(
        self,
        jpeg: bytes,
        source_frame_id: int,
        captured_at: float,
        monotonic_at: float,
        width: int,
        height: int,
        fps: float,
    ) -> None:
        # Jetson UDP recording is performed on Jetson by the split pipeline.
        # The GCS receiver only serves the low-res preview and must never
        # create a second local relay video for this source.
        if self._jetson_recording is not None:
            return
        with self._lock:
            recording_status = self._state["status"]
        if recording_status == "STOPPING":
            self._finish_recording()
            return
        if recording_status not in {"STARTING", "RECORDING"}:
            return

        try:
            import cv2
            import numpy as np

            frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise FlightRecorderError("GStreamer emitted an invalid JPEG frame")
            if recording_status == "STARTING":
                self._begin_recording(cv2, width, height, fps)
            self._record_frame(frame, captured_at, source_frame_id=source_frame_id)
        except Exception as exc:
            self._handle_camera_error(str(exc))

    def _handle_jetson_error(self, error: str) -> None:
        # The Jetson receiver is a preview/telemetry channel. Its packet loss
        # or restart must not finalize the recording that is being written on
        # Jetson. JetsonVideoService exposes RECONNECTING/STALE through
        # status(); only the remote recording agent may end that session.
        with self._lock:
            if self._jetson_video is None:
                self._camera_state.update(
                    camera_running=False,
                    camera_status="FAILED",
                    camera_error=error,
                )

    def _handle_camera_error(self, error: str) -> None:
        with self._lock:
            recording_active = self._state["recording"]
            if self._jetson_video is None:
                self._camera_state.update(
                    camera_running=False,
                    camera_status="FAILED",
                    camera_error=error,
                )
        if recording_active:
            self._finish_recording(error)

    def _publish_easycap_frame(self, jpeg: bytes) -> None:
        with self._frame_ready:
            self._latest_jpeg = jpeg
            self._preview_version += 1
            self._camera_state["preview_frame_count"] += 1
            self._camera_state["frame_count"] += 1
            self._camera_state["last_frame_at_unix"] = time.time()
            self._camera_state["last_frame_timestamp"] = datetime.now(timezone.utc).isoformat()
            self._frame_ready.notify_all()

    def _capture_loop(self):
        capture = None
        try:
            try:
                import cv2
            except ImportError as exc:
                raise FlightRecorderError("opencv-python is not installed in the backend environment") from exc

            backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
            capture = cv2.VideoCapture(self.camera_index, backend)
            if not capture.isOpened():
                raise FlightRecorderError(
                    f"Cannot open EasyCAP/camera index {self.camera_index}; close OBS and verify VRX/EasyCAP"
                )
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.requested_width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.requested_height)
            capture.set(cv2.CAP_PROP_FPS, self.requested_fps)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or self.requested_width)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.requested_height)
            fps = float(capture.get(cv2.CAP_PROP_FPS) or self.requested_fps)
            if fps < 1 or fps > 60:
                fps = self.requested_fps
            self._capture_actual = {"actual_width": width, "actual_height": height, "actual_fps": fps}
            with self._lock:
                self._camera_state.update(
                    camera_running=True,
                    camera_status="LIVE",
                    camera_error=None,
                    width=width,
                    height=height,
                    fps=fps,
                )

            while not self._camera_stop.is_set():
                success, frame = capture.read()
                captured_at = time.time()
                if not success or frame is None:
                    raise FlightRecorderError("EasyCAP stopped returning video frames")
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))

                encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
                if encoded:
                    self._publish_easycap_frame(jpeg.tobytes())

                with self._lock:
                    recording_status = self._state["status"]
                if recording_status == "STARTING":
                    self._begin_recording(cv2, width, height, fps)
                    recording_status = "RECORDING"
                if recording_status == "RECORDING":
                    self._record_frame(frame, captured_at, source_frame_id=None)
                elif recording_status == "STOPPING":
                    self._finish_recording()
        except Exception as exc:
            error = str(exc)
            self._handle_camera_error(error)
        finally:
            if capture is not None:
                capture.release()
            with self._frame_ready:
                if self._camera_state["camera_status"] != "FAILED":
                    self._camera_state.update(camera_running=False, camera_status="STOPPED")
                if self._state["recording"]:
                    self._finish_recording("Camera stopped while recording")
                self._camera_thread = None
                self._frame_ready.notify_all()
