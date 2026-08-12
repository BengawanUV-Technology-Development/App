# Batch 5 Jetson smoke qualification — 2026-08-12

## Result

Batch 5 implementation is deployed and its Jetson-local throughput targets pass
this short smoke test. The Batch 5 acceptance gate remains **pending** because
the Ground receiver/browser was unavailable, so capture-to-browser p95 latency
and decoded-frame identity were not measured end to end.

Tested commit: `2d32e82` (`fix(batch-5): preserve source PTS through preview decimation`)

Mission: `mission-a8152ad7-7487-4247-b689-afb9faf9bfa6`, epoch `0001`

## Model and runtime

- Model: baseline s-YOLOv11, seed 0, 300 epochs
- Checkpoint SHA-256: `dee4c2f026d9058a456f04b723ccc8f5bf5ccfa880f09e88e8dd7169c6120dc0`
- Provenance state: `VERIFIED`
- Ultralytics profile: `imgsz=640`, confidence `0.45`, `cuda:0`, SAHI disabled
- Inference queue: capacity 1, drop oldest / keep newest

## Measured evidence

| Check | Result | Evidence |
| --- | ---: | --- |
| Master recording | 1920×1080, 30.0117 FPS | `ffprobe`; 1,519 frames over 50.613667 s |
| Preview sender cadence | 15.0157 FPS | 1,519 captured - 759 intentional rate drops = 760 preview frames over MP4 duration |
| Inference throughput | 11.6679 FPS | Detector final runtime metadata; 601 processed frames, 0 failures |
| Canonical preview identity | 0 missing | `dropped_preview_identity_missing=0` |
| RTP sender | 8,601 packets, 0 dropped | Final `epoch.json`; no socket errors |
| Per-frame sidecars | Complete | 1,519 `frames.jsonl` and 1,519 `telemetry.jsonl` rows |
| Detection sidecar | Present | 601 `detections.jsonl` rows |
| MP4 finalization | Valid | EOS completed, `ffprobe` read all 1,519 frames |

The 30→15 FPS preview decimation occurs before encoding and preserves source
PTS. Each retained preview access unit is bound to its canonical frame before
RTP packetization; intentional cadence drops are counted separately from
identity failures.

## Tests

- Jetson: 11 `test_arducam_split_pipeline.py` tests passed.
- Local: 11 split-pipeline tests and 5 RTP synchronization tests passed.
- Python compilation and `git diff --check` passed.

## Remaining Batch 5 gate items

- Run the Ground PyGObject receiver and browser canvas together with the Jetson.
- Measure preview average FPS at the decoded receiver, not only sender cadence.
- Measure capture-to-browser p95 latency and prove it is at most 1 second.
- Prove decoded RTP timestamp/frame identity matches detection metadata end to end.
- Exercise detector crash isolation on target hardware.

The backend ingest endpoint was not listening during this smoke run. Publisher
connection errors were isolated and did not interrupt recording, inference, or
RTP sending, but this run is not evidence for the missing Ground/browser gates.

At handoff, recording status was `COMPLETED` with `recording=false`. The v0.3
Recording Agent service remains installed at the tested commit; no Batch 6 work
was started.
