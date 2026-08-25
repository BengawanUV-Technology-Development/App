import json
import re
import tempfile
import unittest
from pathlib import Path

from app.models import TelemetrySample
from app.services.mission_telemetry import MissionTelemetryRecorder
from app.services.readonly_mavlink import ReadonlyMavlinkReceiver
from app.services.time_normalizer import MavlinkTimeNormalizer
from app.utils.state import StateManager
from pymavlink.dialects.v20 import ardupilotmega as mavlink


class R1TelemetryContractTests(unittest.TestCase):
    TEST_MISSION_ID = "mission-11111111-1111-4111-8111-111111111111"

    def test_generated_mission_id_matches_jetson_contract(self):
        with tempfile.TemporaryDirectory(prefix="r1-mission-id-") as temp_dir:
            recorder = MissionTelemetryRecorder(log_dir=temp_dir)
            started = recorder.start()
            mission_id = started["mission_id"]
            recorder.stop()

        self.assertRegex(
            mission_id,
            re.compile(
                r"^mission-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                r"[0-9a-f]{4}-[0-9a-f]{12}$"
            ),
        )

    def test_health_transitions_and_recovery(self):
        state = StateManager()
        receiver = ReadonlyMavlinkReceiver(
            state,
            None,
            "127.0.0.1",
            14551,
            stale_after=3.0,
            disconnected_after=10.0,
        )
        heartbeat = mavlink.MAVLink_heartbeat_message(6, 3, 0, 0, 4, 3)

        receiver._handle_message(
            heartbeat,
            receive_timestamp_ns=1_000_000_000,
            receive_monotonic_ns=1_000_000_000,
        )
        self.assertEqual(state.get().status, "CONNECTED")

        receiver._refresh_connection_state(4_000_001_000)
        self.assertEqual(state.get().status, "STALE")
        self.assertFalse(state.get().connected)

        receiver._refresh_connection_state(11_000_001_000)
        self.assertEqual(state.get().status, "DISCONNECTED")

        receiver._handle_message(
            heartbeat,
            receive_timestamp_ns=12_000_000_000,
            receive_monotonic_ns=12_000_000_000,
        )
        self.assertEqual(state.get().status, "CONNECTED")
        self.assertTrue(state.get().connected)

    def test_timestamp_mapping_does_not_assume_boot_time_is_utc(self):
        normalizer = MavlinkTimeNormalizer()
        attitude = mavlink.MAVLink_attitude_message(2_000, 0.1, 0.2, 0.3, 0, 0, 0)

        before_mapping = normalizer.normalize(attitude)
        self.assertFalse(before_mapping.valid)
        self.assertEqual(before_mapping.clock_domain, "fc_boot_ms")
        self.assertEqual(before_mapping.raw_value, 2_000)

        normalizer.normalize(
            mavlink.MAVLink_system_time_message(1_700_000_000_000_000, 1_000)
        )
        after_mapping = normalizer.normalize(attitude)
        self.assertTrue(after_mapping.valid)
        self.assertEqual(after_mapping.clock_domain, "fc_boot_ms_mapped_to_utc")
        self.assertEqual(after_mapping.timestamp_ns, 1_700_000_001_000_000_000)

    def test_gps_and_quaternion_are_normalized(self):
        state = StateManager()
        receiver = ReadonlyMavlinkReceiver(state, None, "127.0.0.1", 14551)

        gps_sample = receiver._handle_message(
            mavlink.MAVLink_gps_raw_int_message(
                1_700_000_000_000_000,
                3,
                -712345678,
                1101234567,
                123450,
                90,
                120,
                100,
                9000,
                12,
            )
        )
        quaternion_sample = receiver._handle_message(
            mavlink.MAVLink_attitude_quaternion_message(
                2_000,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )
        )

        self.assertIsInstance(gps_sample, TelemetrySample)
        self.assertTrue(gps_sample.source_time_valid)
        self.assertEqual(state.get().gps_fix, 3)
        self.assertEqual(state.get().satellites_visible, 12)
        self.assertEqual(quaternion_sample.payload["quaternion"], [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(state.get().quaternion, [1.0, 0.0, 0.0, 0.0])

    def test_mission_jsonl_is_versioned_and_sample_scoped(self):
        with tempfile.TemporaryDirectory(prefix="r1-mission-log-") as temp_dir:
            recorder = MissionTelemetryRecorder(log_dir=temp_dir)
            started = recorder.start(self.TEST_MISSION_ID)
            sample = TelemetrySample(
                source_timestamp_raw=2_000,
                source_clock_domain="fc_boot_ms",
                receive_timestamp=1_700_000_000_000_000_000,
                receive_monotonic_ns=22,
                source_time_valid=False,
                message_type="ATTITUDE",
                system_id=1,
                component_id=1,
                payload={"roll_deg": 1.0},
            )
            self.assertTrue(recorder.record_sample(sample))
            self.assertTrue(recorder.record_raw_packet(b"\x01\x02", 456, 789))
            stopped = recorder.stop()

            self.assertEqual(started["mission_id"], self.TEST_MISSION_ID)
            self.assertEqual(stopped["mission_id"], self.TEST_MISSION_ID)
            path = Path(stopped["path"])
            self.assertEqual(path.name, "telemetry.jsonl")
            self.assertEqual(path.parent.name, self.TEST_MISSION_ID)
            records = [json.loads(line) for line in path.read_text().splitlines()]

            self.assertEqual(records[0]["schema_version"], 1)
            self.assertEqual(records[0]["record_type"], "mission_event")
            telemetry = next(item for item in records if item["record_type"] == "telemetry_sample")
            self.assertEqual(telemetry["mission_id"], self.TEST_MISSION_ID)
            self.assertEqual(telemetry["message_type"], "ATTITUDE")
            self.assertFalse(telemetry["source_time_valid"])
            self.assertEqual(telemetry["source_timestamp_raw"], 2_000)
            raw = next(item for item in records if item["record_type"] == "raw_mavlink")
            self.assertEqual(raw["payload"]["packet"], "AQI=")
            self.assertEqual(records[-1]["message_type"], "MISSION_END")


if __name__ == "__main__":
    unittest.main()
