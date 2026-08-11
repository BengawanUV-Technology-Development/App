# Production Model Provenance Gate

Checked: 2026-08-11

Batch 5 is blocked. The only baseline checkpoint in the workspace is:

```text
../s-yolov11-ablation/baseline-seed0/weights/best.pt
SHA-256 5fc9c64a1450051452519c181219425dcd3775929aee19f908e196e07df1b282
```

Its internal Ultralytics checkpoint metadata matches the adjacent two-epoch
`args.yaml` and `results.csv`:

- project: `runs/s-yolov11-ablation`
- name: `baseline-seed0`
- epochs: 2
- image size: 640
- seed: 0
- mAP50: 0.06172
- mAP50-95: 0.02899
- checkpoint date: `2026-07-29T05:47:01.802681`

The only baseline log at
`../s-yolov11-ablation/logs/ablation/seed0/baseline.log` describes a different
run:

- project: `runs/s-yolov11-main`
- epochs: 300
- mAP50: 0.478
- mAP50-95: 0.295
- output checkpoint path:
  `runs/s-yolov11-main/baseline-seed0/weights/best.pt`

That 300-epoch checkpoint is not present anywhere in the current workspace.
Therefore the available `best.pt` cannot be authenticated against the supplied
production-run log and must not be selected as the v0.3 production model.

## Evidence required to unblock

Provide the exact checkpoint produced by the 300-epoch baseline log, or provide
the complete training log that produced the existing two-epoch checkpoint.
The selected artifact must have a recorded SHA-256 and internal metadata that
matches its log, configuration, and validation metrics. Once verified, the
Jetson path can be set in `JETSON_MODEL_WEIGHTS` and the hardware FPS/latency
gate can begin.
