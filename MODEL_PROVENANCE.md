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

## Additional candidate supplied for review

The GhostV3 + DWConv candidate was also checked at:

```text
../s-yolov11-ablation/ghostv3_dwconv-seed0/weights/best.pt
SHA-256 f84b7a5f7294edb4d06174c443c7be7455bc413e76233e6a486ec398b9eb8fbe
```

Its internal Ultralytics metadata is self-consistent with the adjacent
`args.yaml` and `results.csv`, but describes a two-epoch ablation run:

- Ultralytics: `8.3.0`
- project: `runs/s-yolov11-ablation`
- name: `ghostv3_dwconv-seed0`
- epochs: 2
- image size: 640
- seed: 0
- classes: 10 VisDrone classes
- mAP50: 0.06098
- mAP50-95: 0.02917
- checkpoint date: `2026-07-29T06:12:38.159789`

The supplied `ghostv3_dwconv.log` describes a different completed run:

- environment: Python `3.11.15`, PyTorch `2.7.1+cu118`, CUDA on RTX A4000
- project: `runs/s-yolov11-main`
- name: `ghostv3_dwconv-seed0`
- epochs completed: 300
- final validation mAP50: 0.460
- final validation mAP50-95: 0.280
- output checkpoint path:
  `runs/s-yolov11-main/ghostv3_dwconv-seed0/weights/best.pt`

The log's 300-epoch checkpoint is also absent from the workspace. In addition,
selecting GhostV3 + DWConv would change the frozen Batch 5 production-model
choice from baseline s-YOLOv11 and therefore requires an explicit contract
decision; the supplied path alone does not authorize that change.

## Evidence required to unblock

For the frozen baseline choice, provide the exact checkpoint produced by the
300-epoch baseline log. If the production choice is intentionally being changed
to GhostV3 + DWConv, first confirm that contract change and provide the exact
checkpoint produced by the 300-epoch GhostV3 + DWConv log. Alternatively, a
two-epoch artifact can only be evaluated as a non-production candidate when its
matching complete training log is supplied.

The selected production artifact must have a recorded SHA-256 and internal
metadata that matches its log, configuration, and validation metrics. Once
verified, the Jetson path can be set in `JETSON_MODEL_WEIGHTS` and the hardware
FPS/latency gate can begin.
