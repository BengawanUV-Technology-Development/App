# Jetson Capture-Only Qualification

Capture-only runs the same production recording and preview branches with the
detector disabled. It is the required first hardware check for a commit.

## Preconditions

- Arducam is visible through Argus.
- `JETSON_RECORD_DIR` is inside the explicitly configured SSD mount.
- Storage guard accepts the mount and reserved free capacity.
- Ground loss must not stop local recording or MAVLink collection.
- Recording-agent and ingest bearer tokens are configured and distinct.

## Evidence layout

```text
mission-<uuid>/
├── mission.json
└── epochs/
    └── 0001/
        ├── video.mp4
        ├── frames.jsonl
        ├── telemetry.jsonl
        ├── detections.jsonl
        └── epoch.json
```

`frames.jsonl` and `telemetry.jsonl` must each contain exactly one v2.0 row per
captured master frame. Capture-only also writes one explicit empty detection
result per frame with coordinate status `not_available`. Join evidence only by
`mission_id + capture_epoch + frame_id + camera_id`; PTS is retained for media
timing, while UTC is timeline/audit data.

## Ten-minute baseline gate

1. Start a new mission through the authenticated Recording Agent.
2. Record at 1920×1080@30 for at least ten minutes with weights disabled.
3. Disconnect the ground network briefly and confirm counters keep advancing.
4. Stop through SIGINT/EOS and validate MP4 `ftyp`, `moov`, and `moof` atoms.
5. Compare frame, telemetry, and placeholder row counts.
6. Save `mission.json`, `epoch.json`, command output, MP4 checksum, and measured
   FPS/storage/resource counters in `PROJECT_STATUS.md`.

Do not check this gate from synthetic tests alone. Coordinate reconstruction is
future work; no coordinate value may be generated for the baseline.
