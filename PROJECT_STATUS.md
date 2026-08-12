# UAV Pipeline v0.3 — Qualification Status

Updated: 2026-08-12

| Batch | Software implementation | Qualification evidence |
| --- | --- | --- |
| 1 Contract/persistence/auth | Implemented | 47 unit tests, Python compile, and Vite build pass; hardware baseline remains external |
| 2 Canonical Jetson identity | Implemented | Synthetic durable epoch/sidecar tests pass; 10-minute Arducam capture remains required |
| 3 RTP-aware receiver | Implemented | Synthetic loss/reorder/duplicate/wrap and 150 ms exact-sync tests pass; target link recovery remains required |
| 4 Browser synchronized overlay | Implemented | Binary-envelope unit test and frontend build pass; browser/target visual test remains required |
| 5 Production detector | Implemented; gate pending | Baseline checkpoint provenance is verified. [File-replay evidence](docs/qualification/BATCH_5_FILE_REPLAY_2026-08-12.md) validates authenticated RTP/Ground flow and isolated live-overlay publishing while exposing persistent-event pressure; browser p95 latency and exact rendered identity still require qualification |
| 6 Reliability/observability | Implementation in progress; gate pending | Added bounded Ground decode-to-publish p50/p95 metrics; 60-minute hardware endurance, network-outage recovery, and full alert coverage remain required |
| 7 Command safety | Not started | SITL qualification required |
| 8 Post-flight workflow | Not started | Import/review tests required |
| 9 Reporting/final E2E | Not started | 60-minute final E2E required |

No hardware gate is considered passed merely because its code or synthetic test
passes. Test commands, checksums, logs, and acceptance reports must be attached
here when executed on the target equipment.

## SAHI and preview-buffering guidance

SAHI is not enabled in the production profile. The current detector uses
full-frame Ultralytics YOLO with `imgsz=640`, and the manifest locks
`sahi=false`.

Adding SAHI does not inherently require a frame buffer, but tiled inference is
expected to increase inference latency. The Ground receiver currently holds a
decoded preview frame for up to 150 ms while waiting for metadata with the
exact same canonical identity. If the bbox arrives within that window, the
frame is published as `MATCHED`; otherwise it is published as
`METADATA_TIMEOUT` without borrowing a bbox from another frame. The RTP jitter
buffer is separate and currently defaults to 80 ms.

Before enabling SAHI, measure inference p50/p95 and end-to-end browser
latency. If SAHI p95 exceeds the 150 ms metadata deadline, use a bounded,
configurable metadata wait window (for example 150–300 ms) only after
qualification shows that the added preview latency is acceptable. Do not add
an unbounded video delay or reuse stale detections. Keep the inference queue
bounded with a drop-oldest/keep-newest policy, and prefer processing a reduced
inference rate (for example 5–10 FPS) over allowing latency to accumulate.

SAHI qualification must verify all of the following:

- inference p95 and capture-to-render browser p95 remain within the accepted
  latency budget;
- `MATCHED`, `METADATA_TIMEOUT`, and late-metadata counters are reported
  separately;
- exact frame identity is preserved when frames are delayed or dropped;
- preview FPS and detector throughput remain acceptable under sustained load.
