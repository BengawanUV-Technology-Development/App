# Production Model Provenance

Verified: 2026-08-11

The v0.3 production detector is the 300-epoch baseline s-YOLOv11 checkpoint.
The artifact was recovered from the Jetson deployment at:

```text
/home/bengawan/yolo11-inference/weights/s-yolov11-baseline-best.pt
SHA-256 dee4c2f026d9058a456f04b723ccc8f5bf5ccfa880f09e88e8dd7169c6120dc0
Size    22858854 bytes
```

The checkpoint is not committed to Git. Its immutable identity and production
runtime profile are frozen in `jetson/production_model.json`; the Recording
Agent and detector pipeline verify the file size and SHA-256 before loading it.

## Checkpoint evidence

Internal Ultralytics metadata:

- architecture: `s-yolov11.yaml`
- project: `runs/s-yolov11-main`
- name: `baseline-seed0`
- epochs: 300 (embedded result history contains epochs 1 through 300)
- image size: 640
- seed: 0
- Ultralytics: `8.3.0`
- checkpoint date: `2026-07-30T13:06:05.830366`
- mAP50: 0.47768
- mAP50-95: 0.29475
- classes: 10 VisDrone classes

These values match
`../s-yolov11-ablation/logs/ablation/seed0/baseline.log`. The production
runtime is fixed to `imgsz=640`, confidence `0.45`, `cuda:0`, and SAHI disabled.

## Rejected artifacts

The checkpoints under `../s-yolov11-ablation/*-seed0/weights/` are two-epoch
ablation/smoke artifacts. They do not match the 300-epoch logs and remain
ineligible for production. The GhostV3 + DWConv 300-epoch checkpoint was lost
with its expired training VPS and is not used by v0.3.

## Remaining qualification

Provenance is verified and no longer blocks the Batch 5 software path. Hardware
qualification still has to demonstrate, with this exact checksum, at least 29
FPS recording, 14.5 FPS preview, 5 inference FPS, and preview latency p95 no
greater than one second. Until those measurements are attached, Batch 5 is
implemented but not hardware-qualified.
