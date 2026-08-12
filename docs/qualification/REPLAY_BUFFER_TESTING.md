# File replay for bbox-buffer qualification

`jetson/replay_vision.py` replays stored `detections.jsonl` metadata to the
Ground overlay endpoint while `arducam_split_pipeline.py` replays a video file
as the preview/RTP source. This is a software qualification tool and does not
replace Arducam, Jetson, network, or browser hardware evidence.

For the normal Jetson setup, use `jetson/replay_recording.sh`. It combines
both processes, reads `JETSON_INGEST_TOKEN` from the root-only systemd
environment file through `sudo` without printing the secret, detects the video
resolution, creates a fresh mission identity, and stops the video process when
the metadata replay ends.

## How it works

1. Run the split pipeline with `--qualification-video` and
   `--allow-qualification-file-source`, without `--weights`. This produces the
   preview/RTP stream and keeps the capture-only path from publishing new
   detector metadata.
2. Run `replay_vision.py` against an existing epoch directory. It reads the
   stored `detections.jsonl`, preserves each exact `frame_id`, and publishes
   rows at the recorded frame timing.
3. Use `--delay-ms` to delay metadata relative to the video. The Ground
   synchronizer currently waits 150 ms before publishing a frame as
   `METADATA_TIMEOUT`.

The replay can override `--mission-id` and `--capture-epoch` so that stored
metadata joins a newly started video replay. The overrides must match the
mission and epoch used by the split pipeline.

## Example

Recommended one-command launcher on `bengawan-desktop`:

```bash
cd /home/bengawan/Documents/App-v03
EPOCH_DIR=/media/bengawan/nopal-ssd1/flight-recordings/mission-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/epochs/0001
jetson/replay_recording.sh \
  "$EPOCH_DIR" \
  --delay-ms 100
```

Repeat with `--delay-ms 0`, `50`, `150`, `200`, and `300`. The launcher uses
the laptop target `100.114.81.87` by default. Override it with
`--ground-host` when needed.

For a standalone video without an inference sidecar, such as
`/home/bengawan/Documents/object_detection_footage_dari_om_buana/video_tf_09082026.mp4`,
run video-only replay:

```bash
jetson/replay_recording.sh \
  /home/bengawan/Documents/object_detection_footage_dari_om_buana/video_tf_09082026.mp4
```

This sends the video/RTP preview but does not publish bbox metadata. To test
the buffer with metadata from another recording, add
`--metadata-epoch /path/to/epoch-0001`; the metadata is remapped to the fresh
mission identity generated for the video replay.

The explicit two-terminal form below remains useful for debugging:

```bash
python jetson/arducam_split_pipeline.py \
  --host <ground-tailscale-ip> \
  --qualification-video /path/input.mp4 \
  --allow-qualification-file-source \
  --mission-id mission-<uuid> \
  --capture-epoch 1 \
  --high-width 1280 --high-height 720 --high-fps 30 \
  --ingest-token "$JETSON_INGEST_TOKEN" \
  --registration-url http://<ground>:5001/api/v1/stream/register \
  --record-dir /tmp/qualification-replay \
  --allow-root-record-dir --min-free-bytes 0
```

In a second terminal, replay the stored metadata with a controlled delay:

```bash
python jetson/replay_vision.py \
  /path/to/old/mission-.../epochs/0001 \
  --overlay-url http://<ground>:5001/api/v1/detection/overlay \
  --token "$JETSON_INGEST_TOKEN" \
  --mission-id mission-<uuid> \
  --capture-epoch 1 \
  --delay-ms 100
```

Repeat with `0`, `50`, `100`, `150`, `200`, and `300` ms. Record Ground
`MATCHED`, `METADATA_TIMEOUT`, late-metadata, decode-to-publish p50/p95, and
browser render metrics for each run. `--dry-run` validates the sidecars and
identity mapping without making HTTP requests.

The tool replays frame-result overlays by default. Pass `--event-url` if the
persistent detection-event path also needs to be exercised.
