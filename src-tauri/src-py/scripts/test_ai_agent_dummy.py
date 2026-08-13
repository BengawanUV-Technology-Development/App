#!/usr/bin/env python3
"""Smoke test for the AI agent pipeline: dummy detection -> Gemini priority
evaluation (app/agents/priority_agent.py) -> Telegram alert
(app/agents/telegram_dispatcher.py).

Uses the real GEMINI_API_KEY/TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID from .env,
so running this sends a REAL message to the configured Telegram chat and
makes a real Gemini API call. It's a manual smoke test, not part of the
automated test suite -- neither agent module is wired into the live
pipeline yet (see docs/post-flight-detection-snapshots.md's sibling
discussion), this just proves the two pieces work and fit together.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.agents.priority_agent import evaluate_detection  # noqa: E402
from app.agents.telegram_dispatcher import send_telegram_alert  # noqa: E402


def main() -> int:
    detection_id = str(uuid.uuid4())
    dummy_ingested_data = {
        "detection_id": detection_id,
        "class": "pedestrian",
        "count": 3,
        "confidence": 0.86,
        "reconstructed_location": {"latitude": -7.5532394, "longitude": 110.8656314},
        "telemetry": {
            "battery_percent": 17,
            "gps_hdop": 1.1,
            "gps_valid": True,
            "altitude_agl_m": 42.0,
        },
        "note": (
            "SYNTHETIC TEST DATA -- not a real detection, sent to verify the "
            "AI agent -> Telegram pipeline end to end."
        ),
    }

    print("[test] calling Gemini for priority evaluation...", flush=True)
    ai_decision = evaluate_detection(dummy_ingested_data)
    print("[test] ai_decision:", json.dumps(ai_decision, indent=2), flush=True)
    if "error" in ai_decision:
        print("[test] evaluate_detection() failed, not sending Telegram alert.", flush=True)
        return 1

    print("[test] sending Telegram alert...", flush=True)
    sent = send_telegram_alert(ai_decision, dummy_ingested_data)
    print("[test] telegram send result:", sent, flush=True)
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
