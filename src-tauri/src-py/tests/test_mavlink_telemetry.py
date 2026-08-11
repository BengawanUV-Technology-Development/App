import json
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[3]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from jetson.arducam_split_pipeline import BoundedSidecarWriter, FramePacket, parse_args  # noqa: E402
from jetson.mavlink_telemetry import (  # noqa: E402
    MAVLinkMessage,
    MAVLinkStreamParser,
    MAVLinkTelemetryCollector,
)


def mavlink_v1(message_id: int, payload: bytes, sequence: int = 1) -> bytes:
    return (
        bytes([0xFE, len(payload), sequence, 1, 1, message_id])
        + payload
        + b"\x00\x00"
    )


def mavlink_v2(message_id: int, payload: bytes, sequence: int = 1) -> bytes:
    return (
        bytes([0xFD, len(payload), 0, 0, sequence, 1, 1])
        + message_id.to_bytes(3, "little")
        + payload
        + b"\x00\x00"
    )


class MAVLinkTelemetryTests(unittest.TestCase):
    def test_parser_handles_split_v1_and_v2_frames(self):
        heartbeat = struct.pack("<IBBBBB", 0, 2, 3, 128, 4, 3)
        stream = mavlink_v1(0, heartbeat) + mavlink_v2(33, b"payload")
        parser = MAVLinkStreamParser()

        messages = []
        for chunk in (stream[:4], stream[4:13], stream[13:]):
            messages.extend(parser.feed(chunk))

        self.assertEqual(
            [(item.message_id, item.system_id, item.component_id) for item in messages],
            [(0, 1, 1), (33, 1, 1)],
        )

    def test_common_messages_produce_reconstruction_telemetry(self):
        collector = MAVLinkTelemetryCollector()
        heartbeat = struct.pack("<IBBBBB", 0, 2, 3, 128, 4, 3)
        global_position = struct.pack(
            "<Iiiii3hH",
            1000,
            -62_000_000,
            106_800_0000,
            123_450,
            50_000,
            300,
            400,
            -20,
            9_000,
        )
        attitude = struct.pack("<Iffffff", 1000, 0.1, -0.2, 1.5707963, 0, 0, 0)

        collector._handle_message(MAVLinkMessage(1, 1, 0, heartbeat))
        collector._handle_message(MAVLinkMessage(1, 1, 33, global_position))
        collector._handle_message(MAVLinkMessage(1, 1, 30, attitude))
        snapshot = collector.snapshot()
        telemetry = snapshot["telemetry"]

        self.assertEqual(snapshot["status"], "RUNNING")
        self.assertTrue(telemetry["connected"])
        self.assertAlmostEqual(telemetry["lat"], -6.2)
        self.assertAlmostEqual(telemetry["lng"], 106.8)
        self.assertAlmostEqual(telemetry["alt"], 50.0)
        self.assertAlmostEqual(telemetry["alt_amsl"], 123.45)
        self.assertAlmostEqual(telemetry["groundspeed_m_s"], 5.0)
        self.assertAlmostEqual(telemetry["v_speed_m_s"], 0.2)
        self.assertAlmostEqual(telemetry["heading_deg"], 90.0)
        self.assertAlmostEqual(telemetry["roll_deg"], 5.729577, places=5)
        self.assertEqual(telemetry["flight_mode"], "STABILIZE")
        self.assertTrue(telemetry["armed"])

    def test_capture_only_writes_explicit_empty_bbox_record(self):
        args = parse_args(["--host", "100.64.0.10"])
        with tempfile.TemporaryDirectory() as temporary:
            collector = MAVLinkTelemetryCollector()
            worker = BoundedSidecarWriter(args, Path(temporary), collector, queue_size=4)
            worker.start()
            now = time.time_ns()
            worker.submit(FramePacket("mission-00000000-0000-0000-0000-000000000001", 1, 7, "arducam", now, time.monotonic_ns(), 123, None))
            worker.close()

            path = Path(temporary) / "detections.jsonl"
            payload = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(payload["frame_id"], 7)
            self.assertEqual(payload["detections"], [])
            self.assertEqual(payload["schema_version"], "2.0")
            self.assertEqual(payload["coordinate"], {"status": "not_available"})
            self.assertEqual(payload["detector"]["reason"], "YOLO_DISABLED_CAPTURE_ONLY")
            self.assertEqual(len((Path(temporary) / "frames.jsonl").read_text().splitlines()), 1)
            self.assertEqual(len((Path(temporary) / "telemetry.jsonl").read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
