import struct
import unittest

from app.services.frame_sync import (
    CanonicalKey,
    FrameSynchronizer,
    RtpIdentityTracker,
    StreamRegistry,
)
from app.services.rtp_identity import RtpTimestampUnwrapper, inject_frame_id, parse_rtp_packet
from jetson.rtp_identity import inject_frame_id as jetson_inject_frame_id


MISSION_ID = "mission-00000000-0000-0000-0000-000000000003"
SSRC = 0xAABBCCDD


def rtp(sequence, timestamp, marker=False, payload=b"h264"):
    return struct.pack("!BBHII", 0x80, (0x80 if marker else 0) | 96, sequence, timestamp, SSRC) + payload


def registry():
    store = StreamRegistry()
    store.register({
        "schema_version": "2.0", "mission_id": MISSION_ID, "capture_epoch": 1,
        "camera_id": "arducam", "ssrc": SSRC, "width": 960, "height": 540,
        "fps": 15, "rtp_clock_rate": 90_000,
    })
    return store


class RtpIdentityTests(unittest.TestCase):
    def test_extension_preserves_rtp_fields_and_payload(self):
        original = rtp(42, 123456, marker=True, payload=b"payload")
        enriched = inject_frame_id(original, 2**40 + 7)
        parsed = parse_rtp_packet(enriched)
        self.assertEqual((parsed.sequence, parsed.timestamp, parsed.ssrc, parsed.frame_id), (42, 123456, SSRC, 2**40 + 7))
        self.assertEqual(enriched[parsed.payload_offset:], b"payload")
        self.assertEqual(enriched, jetson_inject_frame_id(original, 2**40 + 7))

    def test_loss_reorder_duplicate_and_wrap_keep_exact_identity(self):
        tracker = RtpIdentityTracker(registry())
        packets = [
            inject_frame_id(rtp(65534, 0xFFFFFF00), 10),
            inject_frame_id(rtp(0, 0x00000100, marker=True), 12),  # sequence/frame 11 lost
            inject_frame_id(rtp(65535, 0xFFFFFF00, marker=True), 10),  # reordered old frame packet
        ]
        observed = [tracker.observe(packet) for packet in packets]
        self.assertEqual([item[0].frame_id for item in observed], [10, 12, 10])
        self.assertGreater(observed[1][2], observed[0][2])
        self.assertIsNone(tracker.observe(packets[-1]))

    def test_timestamp_unwrap_does_not_move_back_on_reorder(self):
        unwrap = RtpTimestampUnwrapper()
        values = [unwrap.unwrap(value) for value in (0xFFFFFF00, 0x100, 0xFFFFFF80, 0x200)]
        self.assertEqual(values, [0xFFFFFF00, 0x100000100, 0xFFFFFF80, 0x100000200])


class FrameSynchronizerTests(unittest.TestCase):
    def test_exact_metadata_match_and_timeout_never_shift(self):
        sync = FrameSynchronizer(wait_ms=150, capacity=4)
        first = CanonicalKey(MISSION_ID, 1, 1, "arducam")
        second = CanonicalKey(MISSION_ID, 1, 2, "arducam")
        sync.push_video(first, b"jpeg-1", 100, now_ns=1_000_000_000)
        sync.push_video(second, b"jpeg-2", 200, now_ns=1_010_000_000)
        sync.push_metadata({**second.as_dict(), "detections": [{"class": "person"}]}, now_ns=1_020_000_000)
        ready = sync.pop_ready(now_ns=1_160_000_000)
        self.assertEqual([(item.key.frame_id, item.state) for item in ready], [(1, "METADATA_TIMEOUT"), (2, "MATCHED")])
        self.assertFalse(sync.push_metadata({**first.as_dict(), "detections": []}, now_ns=1_170_000_000))
        third = CanonicalKey(MISSION_ID, 1, 3, "arducam")
        sync.push_video(third, b"jpeg-3", 300, now_ns=1_180_000_000)
        self.assertEqual(sync.pop_ready(now_ns=1_180_000_000), [])
        self.assertEqual(sync.stale_metadata_rejected, 1)

    def test_new_stream_registration_replaces_old_ssrc(self):
        store = registry()
        store.register({
            "schema_version": "2.0", "mission_id": MISSION_ID, "capture_epoch": 2,
            "camera_id": "arducam", "ssrc": 7, "width": 960, "height": 540,
            "fps": 15, "rtp_clock_rate": 90_000,
        })
        with self.assertRaisesRegex(ValueError, "unregistered"):
            store.resolve(SSRC, 1)
        self.assertEqual(store.resolve(7, 0)[0].capture_epoch, 2)


if __name__ == "__main__":
    unittest.main()
