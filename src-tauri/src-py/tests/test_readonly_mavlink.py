import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.readonly_mavlink import ReadonlyMavlinkReceiver  # noqa: E402
from app.utils.session_log import SessionLogStore  # noqa: E402
from app.utils.state import StateManager  # noqa: E402
from pymavlink.dialects.v20 import ardupilotmega as mavlink  # noqa: E402


class ReadonlyMavlinkTests(unittest.TestCase):
    def setUp(self):
        self.state = StateManager()
        self.log_dir = tempfile.TemporaryDirectory(prefix="readonly-mavlink-logs-")
        self.logs = SessionLogStore(
            log_dir=self.log_dir.name,
            system_address="udpin://127.0.0.1:14551",
        )

    def tearDown(self):
        self.log_dir.cleanup()

    def test_heartbeat_and_position_update_state(self):
        receiver = ReadonlyMavlinkReceiver(self.state, self.logs, "127.0.0.1", 14551)

        receiver._handle_message(
            mavlink.MAVLink_heartbeat_message(
                6,
                mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                mavlink.MAV_MODE_FLAG_SAFETY_ARMED,
                0,
                4,
                3,
            )
        )
        receiver._handle_message(
            mavlink.MAVLink_global_position_int_message(
                1,
                -712345678,
                1101234567,
                123450,
                23450,
                0,
                0,
                0,
                9000,
            )
        )

        state = self.state.get()
        self.assertTrue(state.connected)
        self.assertEqual(state.status, "ACTIVE")
        self.assertTrue(state.armed)
        self.assertAlmostEqual(state.lat, -71.2345678)
        self.assertAlmostEqual(state.lng, 110.1234567)
        self.assertAlmostEqual(state.alt, 23.45)
        self.assertAlmostEqual(state.alt_amsl, 123.45)
        self.assertEqual(state.source, "mavlink-udp-readonly")

    def test_status_text_is_forwarded_to_read_only_state_only(self):
        receiver = ReadonlyMavlinkReceiver(self.state, self.logs, "127.0.0.1", 14551)

        receiver._handle_message(
            mavlink.MAVLink_statustext_message(
                mavlink.MAV_SEVERITY_WARNING,
                b"PreArm: Waiting for RC\x00",
            )
        )

        state = self.state.get()
        self.assertEqual(state.status_text, "[WARNING] PreArm: Waiting for RC")
        self.assertEqual(
            self.state.get_status_text_history()[0]["text"],
            "PreArm: Waiting for RC",
        )
        self.assertEqual(self.state.get_prearm_texts()[0]["type"], "WARNING")

    def test_vfr_hud_does_not_overwrite_relative_altitude(self):
        receiver = ReadonlyMavlinkReceiver(self.state, self.logs, "127.0.0.1", 14551)

        receiver._handle_message(
            mavlink.MAVLink_global_position_int_message(
                1,
                -712345678,
                1101234567,
                123450,
                23450,
                0,
                0,
                0,
                9000,
            )
        )
        receiver._handle_message(
            mavlink.MAVLink_vfr_hud_message(
                18.5,
                16.0,
                90,
                42,
                999.0,
                1.25,
            )
        )

        state = self.state.get()
        self.assertAlmostEqual(state.alt, 23.45)
        self.assertAlmostEqual(state.alt_amsl, 123.45)
        self.assertAlmostEqual(state.airspeed_m_s, 18.5)
        self.assertAlmostEqual(state.groundspeed_m_s, 16.0)
        self.assertAlmostEqual(state.v_speed_m_s, 1.25)

    def test_udp_receiver_accepts_mavlink_without_replying(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        receiver = ReadonlyMavlinkReceiver(
            self.state,
            self.logs,
            "127.0.0.1",
            port,
            heartbeat_timeout=1.0,
        )
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            receiver.start()
            deadline = time.time() + 2
            while receiver._socket is None and time.time() < deadline:
                time.sleep(0.01)
            self.assertIsNotNone(receiver._socket)

            encoder = mavlink.MAVLink(None)
            encoder.srcSystem = 1
            encoder.srcComponent = 1
            packet = mavlink.MAVLink_heartbeat_message(
                6,
                mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                0,
                0,
                4,
                3,
            ).pack(encoder)
            sender.sendto(packet, ("127.0.0.1", port))

            deadline = time.time() + 2
            while not self.state.get().connected and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.state.get().connected)
            sender.settimeout(0.1)
            with self.assertRaises(socket.timeout):
                sender.recvfrom(1024)
        finally:
            sender.close()
            receiver.stop()


if __name__ == "__main__":
    unittest.main()
