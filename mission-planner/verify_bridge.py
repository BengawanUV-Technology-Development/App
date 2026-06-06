"""Verify a running Mission Planner bridge without sending vehicle commands."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REQUIRED_TELEMETRY_SECTIONS = ("vehicle", "position", "attitude", "velocity", "battery")


def request_json(url, method="GET", payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=3) as response:
        return response.status, json.load(response)


def verify(base_url, test_mode=None):
    health_status, health = request_json(base_url + "/api/v1/health")
    assert health_status == 200
    assert health["ok"] is True
    assert health["service"] == "mission-planner-bridge"

    telemetry_status, telemetry = request_json(base_url + "/api/v1/telemetry")
    assert telemetry_status == 200
    assert telemetry["ok"] is True
    assert isinstance(telemetry["timestamp"], (int, float))
    for section in REQUIRED_TELEMETRY_SECTIONS:
        assert isinstance(telemetry[section], dict), "Missing telemetry section: " + section

    command = None
    if test_mode:
        command_status, command = request_json(
            base_url + "/api/v1/commands/set-flight-mode",
            method="POST",
            payload={"request_id": "bridge-verifier", "mode": test_mode},
        )
        assert command_status == 200
        assert command["ok"] is True
        assert command["command"] == "set-flight-mode"

    print("Bridge contract OK")
    print(json.dumps({"health": health, "telemetry": telemetry, "command": command}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument(
        "--test-mode",
        help="Explicitly send a flight-mode command. Use only with fake bridge or SITL.",
    )
    args = parser.parse_args()

    try:
        verify(args.base_url.rstrip("/"), test_mode=args.test_mode)
    except (AssertionError, HTTPError, URLError, KeyError, ValueError) as exc:
        print("Bridge verification failed: " + str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
