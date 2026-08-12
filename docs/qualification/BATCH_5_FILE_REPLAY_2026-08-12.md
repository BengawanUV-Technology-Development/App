# Batch 5 file-replay qualification — 2026-08-12

## Result

### Execution authorization — 2026-08-12

The operator authorized continued implementation, controlled qualification, and
repository delivery through Git push. This authorization applies to software
and SITL/file-replay execution only. Real-vehicle commands remain blocked by
the Batch 7 SITL gate, and unresolved hardware/browser acceptance items remain
explicitly pending.

The deterministic file-replay path is implemented and exercised from the
Jetson sender through H.264/RTP/UDP, authenticated Ground ingest, PyGObject
decode, and schema-v2 stream registration. The replay is software
qualification evidence only: it is explicitly marked
`hardware_evidence=false` and does not replace the Arducam hardware gates.

Replay exposed shared publisher queue pressure. Live overlay and persistent
detection events now use independent workers and bounded queues:

- overlay: capacity one, drop oldest / keep newest;
- event: separate bounded FIFO with independent pressure counters.

An event backlog can therefore no longer delay or evict the current overlay.

## Source and profile

- Input: `/home/bengawan/Documents/object_detection_footage_dari_om_buana/IMG_5758.MP4`
- Input media: H.264, 1280×720, approximately 30 FPS
- Qualification master: 1280×720 at 30 FPS
- Preview: 960×540 at 15 FPS
- Model: verified baseline s-YOLOv11, seed 0, 300 epochs
- Checkpoint SHA-256: `dee4c2f026d9058a456f04b723ccc8f5bf5ccfa880f09e88e8dd7169c6120dc0`
- Runtime: `imgsz=640`, confidence `0.45`, `cuda:0`, SAHI disabled
- Mission: `mission-57580000-0000-4000-8000-000000000001`

The mode requires both flags and cannot be enabled accidentally:

```text
--qualification-video <path>
--allow-qualification-file-source
```

Without both flags, the production source remains `nvarguscamerasrc`.

## Valid evidence

### Epoch 2 — initial file replay

| Check | Result |
| --- | ---: |
| Status | `COMPLETED` |
| Duration | 60.5667 seconds |
| Master frames / FPS | 1,817 / 30.0306 |
| YOLO frames / FPS | 663 / 10.9288 |
| Inference failures | 0 |
| RTP packets / drops | 10,442 / 0 |
| Sender identity misses | 0 |
| Ground preview FPS | approximately 14.97 |

The shared publisher reached capacity and dropped 1,298 mixed payloads. This
run identified the isolation defect and is not the post-fix acceptance run.

### Epoch 3 — split publisher validation

| Check | Result |
| --- | ---: |
| Status | `COMPLETED` |
| Duration | 62.7000 seconds |
| Master frames / FPS | 1,881 / 30.0285 |
| YOLO frames / FPS | 678 / 10.2968 |
| Inference failures | 0 |
| RTP packets / drops | 10,820 / 0 |
| Sender identity misses | 0 |
| Overlay sent | 645 |
| Overlay keep-newest drops | 32 |
| Persistent events sent | 1,915 |
| Persistent event queue drops | 746 |
| Ground preview FPS at final sample | 14.17 |

The 32 overlay drops are intentional stale-overlay replacement, not shared
queue loss. Persistent event pressure remains visible and isolated. Recording,
inference, RTP, and overlay publication completed despite the event backlog.

## Follow-on Batch 6 implementation

The first observability increment is now implemented in the Ground receiver:
`JetsonVideoService.status()` exposes a bounded
`latency.decode_to_ground_publish` window with count, last, min, p50, p95, and
max milliseconds. The bounded window prevents an extended mission from growing
memory without limit. This is instrumentation only; it does not constitute the
60-minute endurance gate or browser capture-to-render p95 evidence.

The browser path now sends an authenticated, deduplicated render acknowledgement
to `/api/v1/vision/metrics` for each canonical frame. The payload includes
mission, epoch, frame, camera identity, and `receive_to_render_ms`; the backend
exposes the bounded p50/p95 window through the same route. This measures the
browser receive-to-render stage and exact identity coverage. Capture-to-render
qualification still requires a target run that records the resulting metrics
alongside the Ground and Jetson evidence.

## Automated replay artifact validation — 2026-08-12

The stored Epoch 3 artifacts were checked by an automated validator without
rerunning the detector:

| Check | Result |
| --- | ---: |
| Epoch status | `COMPLETED` |
| MP4 frames / sidecar frames | 1,881 / 1,881 |
| Frame identity sequence | unique, monotonic `0..1880` |
| Detection rows | 678, all refer to captured frames |
| Detection IDs | unique |
| Capture FPS | 30.0285 |
| Inference FPS / failures | 10.2968 / 0 |
| RTP packets / drops | 10,820 / 0 |
| Preview identity misses | 0 |

The temporary Ground backend smoke test also confirmed that `/api/v1/vision/metrics`
rejects an unauthenticated POST (`401`), accepts a valid operator metric (`202`),
and rejects a duplicate canonical identity while preserving the original sample.

## Fresh automated capture-only replay — 2026-08-12

The current pipeline source was also exercised directly for a short, standalone
file replay using both qualification guard flags. This run intentionally omitted
`--weights`; it validates capture, recording, sidecars, RTP sender, and identity,
not YOLO performance.

Output:

```text
/media/bengawan/nopal-ssd1/qualification-recordings/
  mission-010b1783-f910-4489-9be8-18d5b40fa9da/epochs/0001/
```

Results: `COMPLETED`, 559 MP4 frames at 1280×720/30 FPS, 559 rows in each of
`frames.jsonl`, `telemetry.jsonl`, and `detections.jsonl`, monotonic frame IDs,
30.1262 capture FPS, 3,351 RTP packets with zero drops, and zero preview
identity misses. The detector is explicitly `DISABLED` in this run, so the
earlier Epoch 3 remains the inference evidence.

Epoch 3 output:

```text
/media/bengawan/nopal-ssd1/qualification-recordings/
  mission-57580000-0000-4000-8000-000000000001/
    epochs/0003/
```

The MP4 contains 1,881 H.264 frames at 1280×720 and 30 FPS. `frames.jsonl` and
`telemetry.jsonl` each contain 1,881 rows; `detections.jsonl` contains 678 rows.

## Visual inference preview

An annotated preview was rendered from the recorded Epoch 3 video and its
exact `detections.jsonl` output. This is a visualization of stored inference
results; it does not rerun the detector and is not additional acceptance
evidence.

```text
Jetson:
/home/bengawan/Documents/object_detection_footage_dari_om_buana/
  hasil_inference_epoch3_preview.mp4
  hasil_inference_epoch3_sample.jpg

Ground laptop:
/Users/ibanana/Downloads/
  hasil_inference_epoch3_preview.mp4
  hasil_inference_epoch3_sample.jpg
```

Preview properties:

| Property | Value |
| --- | ---: |
| Duration | 62.700 seconds |
| Resolution / rate | 1280×720 / 30 FPS |
| Frames | 1,881 |
| Frames with YOLO results | 678 |
| Bounding boxes rendered | 3,107 |

Frames absent from `detections.jsonl` are marked `NO INFERENCE RESULT FOR THIS
FRAME`; they are not presented as inferred frames with zero detections. This
distinction preserves the meaning of the decimated inference schedule.

## Automated checks

- 15 `test_arducam_split_pipeline.py` tests pass on Jetson.
- The same 15 tests pass on the Ground laptop with Python 3.12.
- Python compilation and `git diff --check` pass.

Tests cover the file-source guard, preservation of the split/RTP contract,
overlay drop-oldest/keep-newest behavior, and isolation of event backlog.

## Remaining gate items

This report does not close Batch 5. The following remain:

- separate matched, no-inference, and late-metadata Ground counters;
- measure capture-to-render browser latency p95 at no more than one second;
- capture browser-render evidence for exact decoded frame identity;
- restore decoded preview average to at least 14.5 FPS in the post-fix run;
- qualify detector crash isolation on target hardware;
- address persistent event throughput without coupling it to live overlay.

Arducam capture, Argus behavior, SSD fault behavior, and sensor-to-browser
latency still require hardware evidence.
