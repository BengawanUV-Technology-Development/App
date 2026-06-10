"""Verify a running Mission Planner bridge without sending vehicle commands."""

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REQUIRED_TELEMETRY_SECTIONS = ("vehicle", "position", "attitude", "velocity", "battery")


def request_json(url, method="GET", payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            "{} {} returned HTTP {}: {}".format(method, url, exc.code, response_body)
        )


def normalize_mode(mode):
    return str(mode or "").strip().upper().replace("_", "")


def wait_for_mode(base_url, expected_mode, timeout_seconds):
    deadline = time.time() + timeout_seconds
    last_mode = None
    observed_modes = []

    while time.time() < deadline:
        _, telemetry = request_json(base_url + "/api/v1/telemetry")
        last_mode = telemetry.get("vehicle", {}).get("flight_mode")
        if last_mode not in observed_modes:
            observed_modes.append(last_mode)
        if normalize_mode(last_mode) == normalize_mode(expected_mode):
            return telemetry
        time.sleep(0.25)

    raise RuntimeError(
        "Mission Planner accepted the request, but the flight controller did not "
        "confirm mode {!r} within {:.1f}s. Observed modes: {}. The requested mode "
        "may be unsupported by this vehicle, rejected by a safety check, or "
        "immediately reverted by the flight controller.".format(
            expected_mode,
            timeout_seconds,
            ", ".join(repr(mode) for mode in observed_modes),
        )
    )


def verify(base_url, test_mode=None, test_current_wp=None):
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

    mission_status, mission = request_json(base_url + "/api/v1/mission")
    assert mission_status == 200
    assert mission["ok"] is True
    assert isinstance(mission["waypoints"], list)
    assert "current_seq" in mission

    messages_status, messages = request_json(base_url + "/api/v1/messages")
    assert messages_status == 200
    assert messages["ok"] is True
    assert isinstance(messages["messages"], list)

    command = None
    waypoint_command = None
    if test_mode:
        command_status, command = request_json(
            base_url + "/api/v1/commands/set-flight-mode",
            method="POST",
            payload={"request_id": "bridge-verifier", "mode": test_mode},
        )
        assert command_status == 200
        assert command["ok"] is True
        assert command["command"] == "set-flight-mode"
        telemetry = wait_for_mode(base_url, test_mode, timeout_seconds=5.0)

    if test_current_wp is not None:
        command_status, waypoint_command = request_json(
            base_url + "/api/v1/commands/set-current-waypoint",
            method="POST",
            payload={"request_id": "bridge-verifier-wp", "seq": test_current_wp},
        )
        assert command_status == 200
        assert waypoint_command["ok"] is True
        assert waypoint_command["command"] == "set-current-waypoint"

    print("Bridge contract OK")
    print(json.dumps({"health": health, "telemetry": telemetry, "mission": mission, "messages": messages, "command": command, "waypoint_command": waypoint_command}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument(
        "--test-mode",
        help="Send and confirm a flight-mode command. Use only with fake bridge or SITL.",
    )
    parser.add_argument(
        "--test-current-wp",
        type=int,
        help="Send a set-current-waypoint command. Use only with fake bridge or SITL.",
    )
    args = parser.parse_args()

    try:
        verify(args.base_url.rstrip("/"), test_mode=args.test_mode, test_current_wp=args.test_current_wp)
    except (AssertionError, HTTPError, URLError, KeyError, RuntimeError, ValueError) as exc:
        print("Bridge verification failed: " + str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
