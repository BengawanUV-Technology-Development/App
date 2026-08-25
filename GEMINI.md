# Bengawan UAV/App-v03 — Agent Context

The canonical redevelopment architecture is
[R0_ARCHITECTURE_BASELINE.md](./R0_ARCHITECTURE_BASELINE.md). Read it before
making architecture or integration changes.

## Current runtime boundary

- React talks to the Flask backend over HTTP.
- The Ground router owns the Pixhawk serial connection.
- Flask receives a telemetry-only MAVLink copy on UDP `14551`.
- The configured GCS clients own flight command and mission authority; the
  router supports QGroundControl on UDP `14550` and an optional Mission Planner
  destination on a separately configured UDP port.
- The website must remain monitoring-only for Pixhawk operations.
- Live video currently uses Jetson H.264/RTP/UDP, Ground GStreamer, Flask MJPEG,
  and React `<img>`.

Recording control is a separate, authenticated Ground-to-Jetson operation. The
Ground backend now creates a per-recording `mission_id`, writes a versioned
mission telemetry JSONL, and includes that ID in the Jetson start request. The
remote recording agent has been bench-verified for mission identity,
high-resolution video, frame metadata, source PTS, and sidecar queue health.
Flight acceptance still requires chrony verification, a visible target, and
offline detection synchronization.

## R0 rules

The repository now contains a Jetson-side writer/validator for
`capture_epoch`, `frame_id`, `camera_id`, `capture_utc_ns`,
`capture_monotonic_ns`, and `source_pts_ns`. R1 also implements mission-scoped
`mission_id`, per-sample `source_timestamp`/`receive_timestamp`, source-time
validity, and explicit clock-domain metadata. Do not claim the frame contract
is flight-validated until the flight artifact passes the validator and the
post-flight synchronization acceptance gates.

Ground/Jetson chrony deployment, YOLO,
coordinate reconstruction,
AI Agent, flight commands from the website, MAVLink Anywhere, Internet
fallback, and new WebSocket transports are future work unless a later batch
explicitly changes the scope.

The legacy command-capable service files and the historical checklist in
`src-tauri/src-py/step.md` are reference material only. The production entry
point is the receive-only backend in `src-tauri/src-py/main.py`.

## Development and verification

```bash
npm run build
PYTHONPATH=src-tauri/src-py python3 -m unittest discover \
  -s src-tauri/src-py/tests -p 'test_*.py'
```

Do not perform broad refactors in an R0 documentation/foundation batch.
