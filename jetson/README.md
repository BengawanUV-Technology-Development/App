# Jetson Runtime

This directory is the single source of truth for the Jetson recording,
inference, frame metadata, and camera preview runtime.

## Canonical deployment

The active Jetson checkout is:

```text
/home/bengawan/Documents/app-mavproxy
```

Both systemd services must execute files from that checkout:

| Service | Source file | Purpose |
| --- | --- | --- |
| `buv-recording-agent.service` | `jetson/recording_agent.py` | Authenticated start/stop API and child-process supervision |
| child pipeline | `jetson/arducam_split_pipeline.py` | Arducam capture, high-resolution video, frame metadata, telemetry sidecar, and bounded YOLO |
| `buv-camera-stream.service` | `jetson/camera_stream_service.py` | Low-resolution CSI/EasyCAP H.264/RTP preview |

The checked-in unit files are the production profile for the `bengawan` Jetson:

```text
jetson/buv-recording-agent.service
jetson/buv-camera-stream.service
jetson/buv-recording-agent.storage.conf.example
```

`App-v03` is a retired checkout and must not be used as a systemd
`WorkingDirectory` or `ExecStart` target.

## Machine-only configuration

Do not commit tokens, laptop addresses, or local virtual-environment paths.
The installed services read these files from `/etc/buv`:

```text
/etc/buv/jetson-recording.env
/etc/buv/jetson-recording-target.env
```

The recording environment contains the SSD path, model path, inference runtime,
and capture settings. The target environment contains the Ground callback host
and authentication values. Keep the two files synchronized with the Ground
configuration, but keep their contents out of Git.

The production model itself remains outside this repository, normally at:

```text
/home/bengawan/Documents/s-yolov11-main/ghostv3_dwconv-seed0/weights/best.pt
```

The model manifest in this directory records provenance and expected runtime
settings; it is not a copy of the model weights.

## Mission data location

Recording evidence stays on the Nopal SSD and is not copied to the Ground:

```text
/media/bengawan/nopal-ssd1/flight-recordings/<mission_id>/mission.json
/media/bengawan/nopal-ssd1/flight-recordings/<mission_id>/epochs/<capture_epoch>/video.mp4
/media/bengawan/nopal-ssd1/flight-recordings/<mission_id>/epochs/<capture_epoch>/frames.jsonl
/media/bengawan/nopal-ssd1/flight-recordings/<mission_id>/epochs/<capture_epoch>/telemetry.jsonl
/media/bengawan/nopal-ssd1/flight-recordings/<mission_id>/epochs/<capture_epoch>/detections.jsonl
```

Ground-side telemetry and joined detection artifacts remain in the Ground
backend under `runtime/logs/missions/<mission_id>/`.

## Deployment procedure

From a clean checkout on the Jetson:

```bash
cd /home/bengawan/Documents/app-mavproxy
git pull --ff-only

sudo install -m 0644 jetson/buv-recording-agent.service \
  /etc/systemd/system/buv-recording-agent.service
sudo install -m 0644 jetson/buv-camera-stream.service \
  /etc/systemd/system/buv-camera-stream.service
sudo systemctl daemon-reload
sudo systemctl restart buv-recording-agent.service
sudo systemctl restart buv-camera-stream.service
```

Verify the deployment before flight:

```bash
systemctl is-active buv-recording-agent.service
systemctl is-active buv-camera-stream.service
systemctl cat buv-recording-agent.service
systemctl cat buv-camera-stream.service
```

The camera preview service exits while the recording marker is present so the
recording pipeline can exclusively claim the camera. systemd restarts preview
after recording stops. Do not run a second copy of either service manually.

## Cleanup policy

Mission evidence is never part of source cleanup. Do not delete anything below
`flight-recordings/` as part of a code deployment.

Timestamped source backups (`*.bak-*`, `*~`) are not source files and must not
be committed. If a rollback copy is needed, keep it outside the repository in
a clearly named, dated archive directory.

Run the Jetson unit and Python tests from the repository root:

```bash
PYTHONPATH=. python3 -m unittest discover -s jetson/tests -p 'test_*.py'
```
