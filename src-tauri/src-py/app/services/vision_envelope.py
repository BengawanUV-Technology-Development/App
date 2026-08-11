"""Binary browser envelope: uint32 JSON length, JSON, then matching JPEG."""

from __future__ import annotations

import json
import struct
import time
from typing import Any


class VisionEnvelopeError(ValueError):
    pass


def frame_header(frame, *, preview_width: int, preview_height: int, fps: float, stream_state: str) -> dict[str, Any]:
    metadata = frame.metadata
    detections = metadata.get("detections", []) if isinstance(metadata, dict) else []
    detector_state = (
        str(metadata.get("detector", {}).get("status") or "RUNNING")
        if isinstance(metadata, dict) else "METADATA_TIMEOUT"
    )
    if metadata is None:
        detection_state = "METADATA_TIMEOUT"
    elif detector_state in {"FAILED", "DISABLED"}:
        detection_state = f"DETECTOR_{detector_state}"
    elif detections:
        detection_state = "DETECTED"
    else:
        detection_state = "NO_DETECTION"
    return {
        "schema_version": "2.0",
        **frame.key.as_dict(),
        "rtp_timestamp": frame.rtp_timestamp,
        "preview_width": preview_width,
        "preview_height": preview_height,
        "master_width": int(metadata.get("source_width", 1920)) if metadata else 1920,
        "master_height": int(metadata.get("source_height", 1080)) if metadata else 1080,
        "detections": detections,
        "detector_state": detector_state,
        "detection_state": detection_state,
        "stream_state": stream_state,
        "sync_state": frame.state,
        "fps": fps,
        "ground_queue_latency_ms": max(0.0, (time.monotonic_ns() - frame.decoded_monotonic_ns) / 1_000_000),
        "server_sent_utc_ns": time.time_ns(),
    }


def encode_vision_envelope(frame, **status) -> bytes:
    header = json.dumps(frame_header(frame, **status), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(header) > 1024 * 1024:
        raise VisionEnvelopeError("vision JSON header exceeds 1 MiB")
    return struct.pack("!I", len(header)) + header + frame.jpeg


def decode_vision_envelope(payload: bytes) -> tuple[dict[str, Any], bytes]:
    if len(payload) < 4:
        raise VisionEnvelopeError("vision envelope is truncated")
    length = struct.unpack_from("!I", payload)[0]
    if length > 1024 * 1024 or len(payload) < 4 + length:
        raise VisionEnvelopeError("vision envelope header length is invalid")
    try:
        header = json.loads(payload[4:4 + length].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisionEnvelopeError("vision envelope JSON is invalid") from exc
    jpeg = payload[4 + length:]
    if not (jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")):
        raise VisionEnvelopeError("vision envelope JPEG is invalid")
    return header, jpeg
