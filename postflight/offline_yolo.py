"""Run offline YOLO against a recorded video and emit ``detections.jsonl``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from jetson.frame_metadata import validate_frame_metadata
from postflight.synchronization import load_frame_index


class OfflineYoloError(RuntimeError):
    """Raised when offline inference cannot preserve frame identity."""


def normalize_xyxy(box: Iterable[float], width: int, height: int) -> list[float]:
    values = [float(value) for value in box]
    if len(values) != 4 or width <= 0 or height <= 0:
        raise OfflineYoloError("bbox and image dimensions are invalid")
    x1, y1, x2, y2 = values
    if x2 <= x1 or y2 <= y1:
        raise OfflineYoloError("bbox must have positive width and height")
    normalized = [x1 / width, y1 / height, x2 / width, y2 / height]
    return [max(0.0, min(1.0, value)) for value in normalized]


def build_detection_record(
    *,
    mission_id: str,
    frame: dict[str, Any],
    detection_index: int,
    class_id: int,
    class_name: str,
    confidence: float,
    bbox_xyxy: Iterable[float],
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    box_values = [float(value) for value in bbox_xyxy]
    normalized_box = normalize_xyxy(box_values, image_width, image_height)
    return {
        "schema_version": 1,
        "record_type": "detection",
        "detection_id": f"{mission_id}:{frame['frame_id']}:{detection_index}",
        "mission_id": mission_id,
        "capture_epoch": frame["capture_epoch"],
        "frame_id": frame["frame_id"],
        "camera_id": frame["camera_id"],
        "capture_utc_ns": frame["capture_utc_ns"],
        "source_pts_ns": frame["source_pts_ns"],
        "class_id": class_id,
        "class_name": class_name,
        "confidence": float(confidence),
        "bbox_xyxy": box_values,
        "bbox_xyxy_normalized": normalized_box,
    }


def run_offline_yolo(
    video_path: str | Path,
    frames_path: str | Path,
    output_path: str | Path,
    model_path: str | Path,
    *,
    expected_mission_id: str | None = None,
    confidence: float = 0.25,
    imgsz: int = 640,
    device: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Run one inference call per recorded frame in metadata order.

    The frame index is deliberately driven by ``frames.jsonl`` rather than a
    post-processing wall clock.  A count mismatch is fatal because silently
    shifting detections by one frame would corrupt synchronization.
    """

    video = Path(video_path)
    frames = Path(frames_path)
    output = Path(output_path)
    model = Path(model_path)
    if not video.is_file() or video.stat().st_size <= 0:
        raise OfflineYoloError(f"video is missing or empty: {video}")
    if not model.is_file():
        raise OfflineYoloError(f"YOLO model is missing: {model}")
    if confidence < 0 or confidence > 1:
        raise OfflineYoloError("confidence must be between 0 and 1")
    if imgsz <= 0:
        raise OfflineYoloError("imgsz must be positive")
    if output.exists() and not overwrite:
        raise OfflineYoloError(f"refusing to overwrite detections file: {output}")

    report = validate_frame_metadata(
        frames,
        expected_mission_id=expected_mission_id,
    )
    mission_id = report["mission_id"]
    frame_index = load_frame_index(frames, expected_mission_id=mission_id)
    ordered_frames = [frame_index[frame_id] for frame_id in sorted(frame_index)]

    # Keep heavy dependencies optional for Ground installation and unit tests.
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as exc:
        raise OfflineYoloError(
            "offline YOLO requires both opencv-python and ultralytics"
        ) from exc

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise OfflineYoloError(f"cannot open recorded video: {video}")
    detector = YOLO(str(model))
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = output.open("w" if overwrite else "x", encoding="utf-8")
    frames_processed = 0
    detections_written = 0
    try:
        for frame_meta in ordered_frames:
            ok, image = capture.read()
            if not ok:
                raise OfflineYoloError(
                    f"video ended before frame_id {frame_meta['frame_id']}"
                )
            height, width = image.shape[:2]
            predict_kwargs: dict[str, Any] = {
                "conf": confidence,
                "imgsz": imgsz,
                "verbose": False,
            }
            if device:
                predict_kwargs["device"] = device
            results = detector.predict(image, **predict_kwargs)
            if not results:
                frames_processed += 1
                continue
            result = results[0]
            boxes = getattr(result, "boxes", None)
            if boxes is not None:
                xyxy = _tolist(getattr(boxes, "xyxy", None))
                classes = _scalar_list(getattr(boxes, "cls", None))
                confidences = _scalar_list(getattr(boxes, "conf", None))
                names = getattr(result, "names", None) or getattr(detector, "names", {})
                for index, box in enumerate(xyxy):
                    class_id = int(classes[index])
                    confidence_value = float(confidences[index])
                    class_name = str(names.get(class_id, class_id)) if isinstance(names, dict) else str(class_id)
                    record = build_detection_record(
                        mission_id=mission_id,
                        frame=frame_meta,
                        detection_index=index,
                        class_id=class_id,
                        class_name=class_name,
                        confidence=confidence_value,
                        bbox_xyxy=box,
                        image_width=width,
                        image_height=height,
                    )
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    detections_written += 1
            frames_processed += 1

        extra_ok, _extra_image = capture.read()
        if extra_ok:
            raise OfflineYoloError(
                "video contains more frames than frames.jsonl; "
                "refusing to shift frame identity"
            )
    finally:
        handle.flush()
        handle.close()
        capture.release()

    return {
        "ok": True,
        "mission_id": mission_id,
        "video": str(video),
        "frames_jsonl": str(frames),
        "detections_jsonl": str(output),
        "frames_processed": frames_processed,
        "detections_written": detections_written,
    }


def _tolist(value: Any) -> list[list[float]]:
    if value is None:
        return []
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list):
        return []
    if value and not isinstance(value[0], list):
        return [[float(item)] for item in value]
    return [[float(item) for item in row] for row in value]


def _scalar_list(value: Any) -> list[float]:
    rows = _tolist(value)
    return [row[0] for row in rows if row]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("frames_jsonl", type=Path)
    parser.add_argument("detections_jsonl", type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--mission-id")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = run_offline_yolo(
            args.video,
            args.frames_jsonl,
            args.detections_jsonl,
            args.model,
            expected_mission_id=args.mission_id,
            confidence=args.confidence,
            imgsz=args.imgsz,
            device=args.device,
            overwrite=args.overwrite,
        )
    except (OfflineYoloError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
