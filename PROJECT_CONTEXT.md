# UAV Pipeline v0.3 — Canonical Contract

This file is the source of truth for stable behavior. Runtime qualification and
open evidence belong in `PROJECT_STATUS.md`.

## Release profile

- One active camera: Arducam (`camera_id=arducam`).
- Master evidence: 1920×1080 at 30 FPS.
- Preview: 960×540 at 15 FPS, H.264/RTP/UDP.
- Detector: baseline s-YOLOv11, `imgsz=640`, confidence 0.45, `cuda:0`, SAHI off.
- Coordinate reconstruction is `FUTURE_WORK`; every detection coordinate is
  exactly `{ "status": "not_available" }`.
- Commands are SITL-only until Batch 7 has a signed acceptance report.

## Canonical frame identity

Every captured master frame receives identity before recording, inference, and
preview branches split:

```json
{
  "schema_version": "2.0",
  "mission_id": "mission-<uuid>",
  "capture_epoch": 1,
  "frame_id": 0,
  "camera_id": "arducam",
  "capture_utc_ns": 1786401234281000000,
  "capture_monotonic_ns": 928193821000,
  "source_pts_ns": 0
}
```

One recording session is one mission. The Recording Agent creates the mission
UUID. Epoch starts at one and is stored durably; restart within a mission
increments it. Frame ID starts at zero for each epoch. Live joins use the exact
tuple `(mission_id, capture_epoch, frame_id, camera_id)` plus RTP timestamp.
UTC exists only for timeline/audit and is never a cross-host live matching key.

## Detection and synchronization

Bounding boxes use normalized master-image XYXY with `0 <= x1 < x2 <= 1` and
`0 <= y1 < y2 <= 1`. Each detection has a UUID and canonical frame identity.
RTP carries `frame_id` in a header extension; registration binds SSRC to mission,
epoch, camera, dimensions, FPS, and clock rate. Ground waits at most 150 ms for
exact metadata, then displays the frame without overlay. Late metadata expires
and may never attach to another frame.

The production browser stream is a binary WebSocket envelope:

```text
uint32 big-endian JSON length | UTF-8 JSON header | JPEG bytes
```

The JSON and JPEG always describe the same canonical frame. MJPEG remains a
diagnostic endpoint only.

## Status vocabulary

- Mission: `CREATED`, `RECORDING`, `COMPLETED`, `FAILED`, `IMPORTED`.
- Components: `STARTING`, `RUNNING`, `DEGRADED`, `STALE`, `STOPPING`,
  `STOPPED`, `FAILED`, `DISABLED`.
- Commands: `PENDING`, `SENT`, `ACKNOWLEDGED`, `REJECTED`, `TIMEOUT`, `FAILED`.
- Detector-offline, metadata-timeout, no-detection, and stream-stale are distinct.

## Security and evidence

- `BUV_OPERATOR_TOKEN`: Tauri/operator to ground backend.
- `JETSON_INGEST_TOKEN`: Jetson registration, detections, and health to ground.
- `JETSON_RECORDING_AGENT_TOKEN`: ground backend to Recording Agent.

All mutations and ingest routes require the appropriate bearer token. Operator
tokens live only in application session memory and are never Vite build values.
Original mission evidence is immutable. Imports create checksum-verified working
copies; annotations and reporting state live separately in SQLite.
