# Jetson CV Pipeline v0.3

The only release camera is Arducam. Capture occurs once at 1920×1080@30 FPS and
receives canonical schema v2.0 identity before splitting into three bounded
branches:

```text
Arducam capture + identity
├── fragmented MP4 + frames/telemetry/detections sidecars on mounted SSD
├── newest-frame inference queue → baseline s-YOLOv11
└── 960×540@15 H.264/RTP/UDP preview with frame_id extension
```

Recording and sidecars are independent of ground-network availability. File I/O
does not run in the capture callback. If the configured SSD is not the expected
mount, is not writable, or lacks reserved capacity, recording is rejected and
must never fall back to the root filesystem.

Every detection includes a UUID, exact canonical identity, normalized master
XYXY bounding box, and:

```json
{"coordinate": {"status": "not_available"}}
```

Coordinate reconstruction is intentionally outside v0.3. The detector may not
invent, simulate, or default latitude/longitude. Detector failure degrades only
the detector; recording and preview continue. See `PROJECT_CONTEXT.md` for the
wire contract and `PROJECT_STATUS.md` for measured qualification evidence.
