from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a flight recording into frame-aligned images")
    parser.add_argument("session_dir", type=Path, help="Directory containing video.mp4 and telemetry.jsonl")
    parser.add_argument("--quality", type=int, default=95, help="JPEG quality from 0 to 100")
    args = parser.parse_args()

    try:
        import cv2
    except ImportError as exc:
        raise SystemExit("opencv-python is required") from exc

    session_dir = args.session_dir.resolve()
    video_path = session_dir / "video.mp4"
    telemetry_path = session_dir / "telemetry.jsonl"
    if not video_path.exists() or not telemetry_path.exists():
        raise SystemExit("The session must contain video.mp4 and telemetry.jsonl")

    telemetry_by_frame = {}
    with telemetry_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                telemetry_by_frame[int(item["frame_id"])] = item

    frames_dir = session_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    manifest_path = frames_dir / "frames.jsonl"
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise SystemExit(f"Cannot open {video_path}")

    frame_id = 0
    with manifest_path.open("w", encoding="utf-8") as manifest:
        while True:
            success, frame = capture.read()
            if not success:
                break
            filename = f"frame_{frame_id:08d}.jpg"
            if not cv2.imwrite(str(frames_dir / filename), frame, [cv2.IMWRITE_JPEG_QUALITY, args.quality]):
                capture.release()
                raise SystemExit(f"Cannot write {filename}")
            telemetry = telemetry_by_frame.get(frame_id)
            manifest.write(json.dumps({
                "frame_id": frame_id,
                "image": filename,
                "captured_at_unix": telemetry.get("captured_at_unix") if telemetry else None,
                "telemetry_available": telemetry is not None,
            }) + "\n")
            frame_id += 1

    capture.release()
    print(f"Extracted {frame_id} frames to {frames_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
