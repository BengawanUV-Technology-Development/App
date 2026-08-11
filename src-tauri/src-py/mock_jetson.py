"""Send one schema-v2 detection event for authenticated backend testing."""

from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid


API_URL = "http://127.0.0.1:5001/api/v1/detection/ingest"
MISSION_ID = "mission-00000000-0000-0000-0000-000000000099"


def send_mock_detection() -> None:
    token = os.getenv("JETSON_INGEST_TOKEN", "").strip()
    if not token:
        raise SystemExit("JETSON_INGEST_TOKEN must be set for the authenticated ingest test")
    now_ns = time.time_ns()
    payload = {
        "schema_version": "2.0",
        "type": "vision.detection_event",
        "mission_id": MISSION_ID,
        "capture_epoch": 1,
        "frame_id": 0,
        "camera_id": "arducam",
        "capture_utc_ns": now_ns,
        "capture_monotonic_ns": time.monotonic_ns(),
        "source_pts_ns": 0,
        "detection_id": str(uuid.uuid4()),
        "class": "person",
        "confidence": 0.89,
        "bbox_normalized_xyxy": [0.25, 0.2, 0.55, 0.8],
        "coordinate": {"status": "not_available"},
    }

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    print(f"Sending schema-v2 mock detection to {API_URL}...")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
            print(f"HTTP {response.status}: {json.dumps(body, indent=2)}")
    except Exception as exc:
        print(f"Connection failed: {exc}. Is the Flask backend running?")


if __name__ == "__main__":
    send_mock_detection()
