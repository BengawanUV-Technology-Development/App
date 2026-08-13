# Post-flight detection snapshots (map hover UX)

Design decisions from the 2026-08-14 session, recorded so the reasoning
survives past the conversation that produced it.

## Goal

Operator hovers a detected-target pin on `OperationalMap.jsx` and sees the
actual camera frame (with the bounding box drawn on it) that produced that
detection, plus its estimated coordinate.

## Decisions made and why

**Post-flight, not live.** Earlier in this session we built (and then
partly walked back) a live "hold the video frame until its bbox arrives"
join in `FrameSynchronizer`. That approach forces the *entire* live video
feed to lag by the join window (150-700ms tried), because every frame is
held pending a possible match, not just the ones that end up matched. The
operator explicitly chose to accept snapshot delay in exchange for a live
feed with zero added latency: video is shown the instant it decodes, full
stop. Detection review moves to after landing instead of fighting network
jitter in real time.

**Store `frame_id` + bbox + coordinate, not the image.** The full frame
already exists in the flight recording's `video.mp4` once the flight ends.
Storing a live snapshot cache during flight was unnecessary complexity for
a feature that isn't needed until after landing. Post-flight, a frame is
recovered by seeking `video.mp4` at the recorded `frame_id`.

**Low resolution is acceptable.** The evidentiary/high-res material stays
in `video.mp4` on the Jetson (see the operator runbook). This feature is a
convenience UX for the operator, not the scoring artifact, so a smaller
generated JPEG is fine.

**Process on the Jetson, ship only the small result.** `video.mp4` can be
gigabytes; the Jetson already has it locally with nothing to transfer.
Generating small crops+manifest on the Jetson and shipping only that
(likely low tens of MB even for hundreds of detections) avoids moving the
full recording over a link this session repeatedly found to be slow or
unstable (Tailscale DERP relay; even the "same LAN" case turned out to be
AP-isolated). Processing on the ground first (transfer-then-process) would
have made the large `video.mp4` transfer the bottleneck.

**Coordinate reconstruction uses the Jetson's own `telemetry.jsonl`, not
ground's Mission Planner log.** Both exist independently (see the earlier
telemetry architecture discussion). Using the Jetson's own onboard
telemetry for this offline pass sidesteps the Jetson<->ground clock-skew
question entirely, since every timestamp involved is from the Jetson's own
clock. (The clock-offset handshake for the *live*, cross-machine ground
telemetry join is being handled in a separate branch to be merged later --
out of scope here.)

## Pipeline

```
[Jetson, after a recording stops]
  recording_agent.py's stop() finishes
    -> spawns jetson/generate_detection_snapshots.py <epoch_dir> in the background
         reads detections.jsonl (frame_id, bbox, class, confidence)
         reads telemetry.jsonl (Jetson onboard MAVLink) for coordinate estimation
         seeks video.mp4 at each detection's frame_id, crops + draws the bbox
         writes <epoch_dir>/postflight/manifest.jsonl + snapshots/<detection_id>.jpg
    -> POSTs the manifest + small jpegs to the ground backend
         (new endpoint, ingest-token authenticated, same pattern as
         stream/register and detection/overlay)

[Ground/Mac]
  new DB table stores the manifest rows; jpegs saved under runtime/
  GET endpoint lists detections with coordinates for map pins
  GET endpoint serves one detection's jpeg for the hover popup

[Frontend]
  OperationalMap.jsx plots a pin per detection with a valid coordinate
  hovering a pin fetches and shows its snapshot jpeg (bbox already drawn in)
```

## Explicitly out of scope here

- Live bbox overlay tuning (BUV_VISION_SYNC_WAIT_MS) -- already shipped
  separately, left as-is (opportunistic best-effort live match).
- Jetson<->ground clock-offset handshake -- separate branch, to be merged.
- Automatic cleanup/retention policy for accumulated snapshots across many
  flights -- not decided yet, flagged for a follow-up conversation.
