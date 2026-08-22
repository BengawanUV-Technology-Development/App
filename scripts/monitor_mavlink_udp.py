#!/usr/bin/env python3
"""Print decoded MAVLink packets received on a UDP port."""

from __future__ import annotations

import argparse
import time

from pymavlink import mavutil


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=14551)
    parser.add_argument(
        "--all",
        action="store_true",
        help="print every decoded MAVLink message instead of common telemetry only",
    )
    args = parser.parse_args()

    connection = mavutil.mavlink_connection(f"udpin:{args.host}:{args.port}")
    print(f"Listening for MAVLink on UDP {args.host}:{args.port}", flush=True)
    print("Press Ctrl-C to stop.", flush=True)

    common = {
        "HEARTBEAT",
        "VFR_HUD",
        "GLOBAL_POSITION_INT",
        "ATTITUDE",
        "GPS_RAW_INT",
        "SYS_STATUS",
        "BATTERY_STATUS",
        "RC_CHANNELS",
        "STATUSTEXT",
    }

    try:
        while True:
            message = connection.recv_match(blocking=True, timeout=1)
            if message is None or message.get_type() == "BAD_DATA":
                continue
            if not args.all and message.get_type() not in common:
                continue

            timestamp = time.strftime("%H:%M:%S")
            source = f"{message.get_srcSystem()}:{message.get_srcComponent()}"
            print(f"[{timestamp}] {source} {message.get_type()} {message.to_dict()}", flush=True)
    except KeyboardInterrupt:
        print("Monitor stopped", flush=True)
    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
