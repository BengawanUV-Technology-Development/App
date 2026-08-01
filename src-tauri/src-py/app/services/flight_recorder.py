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


class FlightRecorderError(RuntimeError):
    pass


class FlightRecorder:
    """One EasyCAP owner shared by MJPEG preview and the flight recorder."""

    def __init__(self, telemetry_provider: Callable[[], dict], recordings_dir: str | Path | None = None):
        self.telemetry_provider = telemetry_provider
        self.recordings_dir = Path(
            recordings_dir or os.getenv("FLIGHT_RECORDINGS_DIR") or Path.cwd() / "recordings"
        ).resolve()
        self.camera_index = int(os.getenv("VRX_CAMERA_INDEX", "0"))
        self.requested_width = int(os.getenv("VRX_CAPTURE_WIDTH", "640"))
        self.requested_height = int(os.getenv("VRX_CAPTURE_HEIGHT", "480"))
        self.requested_fps = float(os.getenv("VRX_CAPTURE_FPS", "25"))
        self.video_standard = os.getenv("VRX_VIDEO_STANDARD", "PAL")
        self.codec = os.getenv("VRX_VIDEO_CODEC", "mp4v")
        self.jpeg_quality = int(os.getenv("VRX_PREVIEW_JPEG_QUALITY", "75"))

        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._camera_stop = threading.Event()
        self._camera_thread: threading.Thread | None = None
        self._latest_jpeg: bytes | None = None
        self._preview_version = 0
        self._camera_state = self._empty_camera_state()
        self._state = self._idle_recording_state()

        # These resources are created and used by the capture thread only.
        self._writer = None
        self._telemetry_file = None
        self._recording_monotonic_start: float | None = None
        self._capture_actual: dict = {}

    @staticmethod
    def _empty_camera_state() -> dict:
        return {
            "camera_running": False,
            "camera_status": "STOPPED",
            "camera_error": None,
            "camera_index": None,
            "width": None,
            "height": None,
            "fps": None,
            "preview_frame_count": 0,
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
        with self._lock:
            state = {**self._state, **self._camera_state}
        if state["recording"] and state["started_at"]:
            state["duration_seconds"] = max(0, time.time() - state["started_at"])
        else:
            start, end = state.get("started_at"), state.get("ended_at")
            state["duration_seconds"] = max(0, end - start) if start and end else 0
        return state

    def start_camera(self) -> dict:
        with self._lock:
            if self._camera_thread and self._camera_thread.is_alive():
                return self.status()
            self._camera_stop.clear()
            self._latest_jpeg = None
            self._camera_state = {
                **self._empty_camera_state(),
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
        with self._lock:
            if self._state["recording"]:
                raise FlightRecorderError("Stop and save the active recording before stopping the camera")
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
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            elif camera_status in {"FAILED", "STOPPED"}:
                return

    def start(self, label: str | None = None) -> dict:
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
        self.start_camera()
        return self.status()

    def stop(self) -> dict:
        with self._frame_ready:
            if not self._state["recording"]:
                raise FlightRecorderError("No flight recording is active")
            self._state["status"] = "STOPPING"
            completed = self._frame_ready.wait_for(lambda: not self._state["recording"], timeout=10)
        if not completed:
            raise FlightRecorderError("Recorder did not stop within 10 seconds")
        return self.status()

    def _write_metadata(self, path: Path):
        state = self.status()
        metadata = {
            "schema_version": "1.0",
            "session_id": state["session_id"],
            "label": state.get("label"),
            "status": state["status"],
            "started_at_unix": state["started_at"],
            "started_at_iso": datetime.fromtimestamp(state["started_at"], timezone.utc).isoformat() if state["started_at"] else None,
            "ended_at_unix": state["ended_at"],
            "ended_at_iso": datetime.fromtimestamp(state["ended_at"], timezone.utc).isoformat() if state["ended_at"] else None,
            "frame_count": state["frame_count"],
            "duration_seconds": state["duration_seconds"],
            "synchronization": {
                "key": "frame_id",
                "description": "Each telemetry.jsonl row describes the sensor snapshot captured for the matching encoded video frame.",
                "timestamps": ["captured_at_unix", "elapsed_monotonic_seconds"],
            },
            "files": {"video": "video.mp4", "telemetry": "telemetry.jsonl", "metadata": "metadata.json"},
            "capture": {
                "device": "VRX RD945 via EasyCAP",
                "camera_index": self.camera_index,
                "requested_width": self.requested_width,
                "requested_height": self.requested_height,
                "requested_fps": self.requested_fps,
                "video_standard": self.video_standard,
                "codec": self.codec,
                **self._capture_actual,
            },
            "host": {"system": platform.system(), "release": platform.release()},
            "error": state["error"],
        }
        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(path)

    def _begin_recording(self, cv2, width: int, height: int, fps: float):
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
        self._telemetry_file = (session_dir / "telemetry.jsonl").open("a", encoding="utf-8", buffering=1)
        self._recording_monotonic_start = time.monotonic()
        with self._lock:
            self._state["status"] = "RECORDING"
        self._write_metadata(session_dir / "metadata.json")

    def _record_frame(self, frame, captured_at: float):
        self._writer.write(frame)
        with self._lock:
            frame_id = self._state["frame_count"]
            self._state["frame_count"] += 1
        snapshot = self.telemetry_provider()
        row = {
            "frame_id": frame_id,
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
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        if self._telemetry_file is not None:
            self._telemetry_file.close()
            self._telemetry_file = None
        with self._frame_ready:
            session_dir = self._state.get("session_dir")
            self._state.update(
                recording=False,
                status="FAILED" if error else "COMPLETED",
                ended_at=time.time(),
                error=error,
            )
            self._frame_ready.notify_all()
        if session_dir:
            self._write_metadata(Path(session_dir) / "metadata.json")

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
                    with self._frame_ready:
                        self._latest_jpeg = jpeg.tobytes()
                        self._preview_version += 1
                        self._camera_state["preview_frame_count"] += 1
                        self._frame_ready.notify_all()

                with self._lock:
                    recording_status = self._state["status"]
                if recording_status == "STARTING":
                    self._begin_recording(cv2, width, height, fps)
                    recording_status = "RECORDING"
                if recording_status == "RECORDING":
                    self._record_frame(frame, captured_at)
                elif recording_status == "STOPPING":
                    self._finish_recording()
        except Exception as exc:
            error = str(exc)
            with self._lock:
                recording_active = self._state["recording"]
                self._camera_state.update(camera_running=False, camera_status="FAILED", camera_error=error)
            if recording_active:
                self._finish_recording(error)
        finally:
            if capture is not None:
                capture.release()
            with self._frame_ready:
                if self._camera_state["camera_status"] != "FAILED":
                    self._camera_state.update(camera_running=False, camera_status="STOPPED")
                if self._state["recording"]:
                    self._finish_recording("Camera stopped while recording")
                self._frame_ready.notify_all()
