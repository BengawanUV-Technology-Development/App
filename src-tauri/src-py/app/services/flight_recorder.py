from __future__ import annotations

import json
import os
import platform
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


class FlightRecorderError(RuntimeError):
    pass


class FlightRecorder:
    """Owns the capture device and writes frame-aligned telemetry."""

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
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = self._idle_state()

    @staticmethod
    def _idle_state() -> dict:
        return {
            "recording": False,
            "status": "IDLE",
            "session_id": None,
            "session_dir": None,
            "started_at": None,
            "ended_at": None,
            "frame_count": 0,
            "error": None,
        }

    def status(self) -> dict:
        with self._lock:
            state = dict(self._state)
        if state["recording"] and state["started_at"]:
            state["duration_seconds"] = max(0, time.time() - state["started_at"])
        else:
            start = state.get("started_at")
            end = state.get("ended_at")
            state["duration_seconds"] = max(0, end - start) if start and end else 0
        return state

    def start(self, label: str | None = None) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise FlightRecorderError("A flight recording is already active")

            now = datetime.now(timezone.utc)
            safe_stamp = now.strftime("%Y%m%dT%H%M%SZ")
            session_id = f"flight-{safe_stamp}-{uuid.uuid4().hex[:8]}"
            session_dir = self.recordings_dir / session_id
            session_dir.mkdir(parents=True, exist_ok=False)
            self._stop_event.clear()
            self._state = {
                **self._idle_state(),
                "recording": True,
                "status": "STARTING",
                "session_id": session_id,
                "session_dir": str(session_dir),
                "started_at": now.timestamp(),
                "label": (label or "").strip() or None,
            }
            self._thread = threading.Thread(
                target=self._record_loop,
                args=(session_dir,),
                daemon=True,
                name=f"flight-recorder-{session_id}",
            )
            self._thread.start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                raise FlightRecorderError("No flight recording is active")
            self._state["status"] = "STOPPING"
            self._stop_event.set()
        thread.join(timeout=10)
        if thread.is_alive():
            raise FlightRecorderError("Recorder did not stop within 10 seconds")
        return self.status()

    def _write_metadata(self, path: Path, extra: dict | None = None):
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
            },
            "host": {"system": platform.system(), "release": platform.release()},
            "error": state["error"],
        }
        if extra:
            metadata.update(extra)
        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(path)

    def _record_loop(self, session_dir: Path):
        capture = None
        writer = None
        metadata_path = session_dir / "metadata.json"
        telemetry_path = session_dir / "telemetry.jsonl"
        actual_capture = {}
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

            writer = cv2.VideoWriter(
                str(session_dir / "video.mp4"),
                cv2.VideoWriter_fourcc(*self.codec),
                fps,
                (width, height),
            )
            if not writer.isOpened():
                raise FlightRecorderError(f"Cannot create video.mp4 with codec {self.codec}")

            actual_capture = {"actual_width": width, "actual_height": height, "actual_fps": fps}
            with self._lock:
                self._state["status"] = "RECORDING"
            self._write_metadata(metadata_path, {"capture_actual": actual_capture})

            start_monotonic = time.monotonic()
            with telemetry_path.open("a", encoding="utf-8", buffering=1) as telemetry_file:
                while not self._stop_event.is_set():
                    success, frame = capture.read()
                    captured_at = time.time()
                    elapsed = time.monotonic() - start_monotonic
                    if not success or frame is None:
                        raise FlightRecorderError("EasyCAP stopped returning video frames")
                    if frame.shape[1] != width or frame.shape[0] != height:
                        frame = cv2.resize(frame, (width, height))

                    writer.write(frame)
                    with self._lock:
                        frame_id = self._state["frame_count"]
                        self._state["frame_count"] += 1
                    snapshot = self.telemetry_provider()
                    row = {
                        "frame_id": frame_id,
                        "captured_at_unix": captured_at,
                        "elapsed_monotonic_seconds": elapsed,
                        "telemetry_version": snapshot.get("version"),
                        "telemetry_received_at_unix": snapshot.get("timestamp"),
                        "telemetry_stale": snapshot.get("stale"),
                        "gps_valid": snapshot.get("gps_valid"),
                        "telemetry": snapshot.get("telemetry", snapshot),
                    }
                    telemetry_file.write(json.dumps(row, ensure_ascii=False) + "\n")

            with self._lock:
                self._state.update(recording=False, status="COMPLETED", ended_at=time.time())
        except Exception as exc:
            with self._lock:
                self._state.update(recording=False, status="FAILED", ended_at=time.time(), error=str(exc))
        finally:
            if capture is not None:
                capture.release()
            if writer is not None:
                writer.release()
            self._write_metadata(metadata_path, {"capture_actual": actual_capture})

