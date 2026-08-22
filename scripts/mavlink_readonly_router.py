#!/usr/bin/env python3
"""Restricted MAVLink fan-out for macOS, Linux, and Windows.

The QGroundControl path is bidirectional: telemetry is sent to QGC and MAVLink
packets received on QGC's learned UDP source port are written to the flight
controller.

The web path is intentionally transmit-only. The web UDP socket is never
bound or read by this process, so packets sent by the web application cannot
be forwarded to the flight controller.
"""

from __future__ import annotations

import argparse
import os
import select
import signal
import socket
import sys
import threading
from typing import Tuple

from pymavlink import mavutil


Address = Tuple[str, int]


def parse_address(value: str) -> Address:
    host, separator, port = value.rpartition(":")
    if not separator or not host:
        raise argparse.ArgumentTypeError("address must be HOST:PORT")
    try:
        return host, int(port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serial",
        default=os.environ.get("MAVLINK_SERIAL_PORT", "/dev/cu.usbserial-DU0E7WRJ"),
        help="flight-controller serial device (macOS/Linux: /dev/...; Windows: COM5)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=int(os.environ.get("MAVLINK_SERIAL_BAUD", "57600")),
        help="flight-controller serial baudrate",
    )
    parser.add_argument(
        "--qgc",
        type=parse_address,
        default=parse_address(os.environ.get("MAVLINK_QGC_ADDRESS", "127.0.0.1:14550")),
        help="QGroundControl destination (default: 127.0.0.1:14550)",
    )
    parser.add_argument(
        "--web",
        type=parse_address,
        default=parse_address(os.environ.get("MAVLINK_WEB_ADDRESS", "127.0.0.1:14551")),
        help="read-only web destination (default: 127.0.0.1:14551)",
    )
    args = parser.parse_args()

    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    print(f"Opening MAVLink serial {args.serial} at {args.baud}", flush=True)
    master = mavutil.mavlink_connection(
        args.serial,
        baud=args.baud,
        autoreconnect=True,
        source_system=255,
    )

    # Keep the blocking serial read bounded so Ctrl-C can stop the reader.
    port = getattr(master, "port", None)
    if port is not None and hasattr(port, "timeout"):
        port.timeout = 0.5

    # This socket is bound to an ephemeral port. QGC replies to the source
    # port from which it receives telemetry, giving QGC a two-way path without
    # making the router compete with QGC for UDP/14550.
    qgc_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    qgc_socket.bind(("127.0.0.1", 0))
    qgc_socket.setblocking(False)

    # Deliberately no bind(), recv(), or select() is performed on this socket.
    # It is an output-only path for the web application.
    web_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    qgc_address = args.qgc
    web_address = args.web
    print(
        f"QGC: bidirectional via {qgc_address[0]}:{qgc_address[1]} "
        f"(router source port {qgc_socket.getsockname()[1]})",
        flush=True,
    )
    print(
        f"Web: telemetry-only to {web_address[0]}:{web_address[1]} "
        "(incoming web UDP is not read)",
        flush=True,
    )

    def forward_serial() -> None:
        announced_vehicle = False
        while not stop.is_set():
            try:
                message = master.recv_msg()
            except Exception as exc:
                if not stop.is_set():
                    print(f"Serial read error: {exc}", file=sys.stderr, flush=True)
                continue
            if message is None or message.get_type() == "BAD_DATA":
                continue

            packet = message.get_msgbuf()
            try:
                qgc_socket.sendto(packet, qgc_address)
                web_socket.sendto(packet, web_address)
            except OSError as exc:
                if not stop.is_set():
                    print(f"UDP send error: {exc}", file=sys.stderr, flush=True)

            if not announced_vehicle and message.get_type() == "HEARTBEAT":
                announced_vehicle = True
                print(
                    "Heartbeat received: "
                    f"system={message.get_srcSystem()} "
                    f"component={message.get_srcComponent()} "
                    f"type={message.type}",
                    flush=True,
                )

    serial_thread = threading.Thread(target=forward_serial, name="mavlink-serial", daemon=True)
    serial_thread.start()

    try:
        while not stop.is_set():
            try:
                readable, _, _ = select.select([qgc_socket], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not readable:
                continue

            try:
                packet, sender = qgc_socket.recvfrom(65535)
            except BlockingIOError:
                continue
            if not packet:
                continue

            # Only QGC's learned return path reaches this socket. The web
            # destination has no corresponding receive path by design.
            try:
                master.write(packet)
            except Exception as exc:
                print(f"QGC-to-serial write error from {sender}: {exc}", file=sys.stderr, flush=True)
    finally:
        stop.set()
        serial_thread.join(timeout=1.5)
        qgc_socket.close()
        web_socket.close()
        master.close()
        print("Router stopped", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
