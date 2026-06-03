import asyncio
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VENV_SITE_PACKAGES = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
if VENV_SITE_PACKAGES.exists() and str(VENV_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(VENV_SITE_PACKAGES))

from app.services.command import CommandService
from app.utils.errors import CommandTimeoutError, InvalidRequestError, NotConnectedError
from app.utils.state import StateManager
from app.validators import CommandValidator


class FakeAction:
    def __init__(self):
        self.calls = []

    async def arm(self):
        self.calls.append("arm")

    async def disarm(self):
        self.calls.append("disarm")

    async def takeoff(self):
        self.calls.append("takeoff")

    async def land(self):
        self.calls.append("land")

    async def hold(self):
        self.calls.append("hold")

    async def return_to_launch(self):
        self.calls.append("return_to_launch")

    async def transition_to_fixedwing(self):
        self.calls.append("transition_to_fixedwing")

    async def transition_to_multicopter(self):
        self.calls.append("transition_to_multicopter")

    async def reboot(self):
        self.calls.append("reboot")

    async def set_takeoff_altitude(self, altitude):
        self.calls.append(("set_takeoff_altitude", altitude))


class FakeMavlinkDirect:
    def __init__(self):
        self.calls = []

    async def send_message(self, message):
        self.calls.append(("send_message", message))


class FakeDrone:
    def __init__(self):
        self._action = FakeAction()
        self._mavlink_direct = FakeMavlinkDirect()

    @property
    def action(self):
        return self._action

    @property
    def mavlink_direct(self):
        return self._mavlink_direct


class DisconnectingRebootAction(FakeAction):
    async def reboot(self):
        self.calls.append("reboot")
        raise RuntimeError("UNAVAILABLE: connection reset by remote host")


class DisconnectingRebootDrone(FakeDrone):
    def __init__(self):
        self._action = DisconnectingRebootAction()
        self._mavlink_direct = FakeMavlinkDirect()


class CommandValidatorTests(unittest.TestCase):
    def setUp(self):
        self.state_manager = StateManager()
        self.validator = CommandValidator(self.state_manager)

    def test_validate_is_connected_raises_when_disconnected(self):
        with self.assertRaises(NotConnectedError):
            self.validator.validate_is_connected()

    def test_validate_takeoff_request_returns_float_when_valid(self):
        self.state_manager.update(connected=True)

        result = self.validator.validate_takeoff_request("10")

        self.assertEqual(result, 10.0)

    def test_validate_takeoff_request_rejects_invalid_altitude(self):
        self.state_manager.update(connected=True)

        with self.assertRaises(InvalidRequestError):
            self.validator.validate_takeoff_request("abc")

        with self.assertRaises(InvalidRequestError):
            self.validator.validate_takeoff_request(1)

        with self.assertRaises(InvalidRequestError):
            self.validator.validate_takeoff_request(51)


class CommandServiceTests(unittest.TestCase):
    def setUp(self):
        self.state_manager = StateManager()
        self.state_manager.update(connected=True)
        self.drone = FakeDrone()
        self.service = CommandService(self.state_manager, lambda: self.drone)

    def test_execute_arm_calls_mavsdk_arm(self):
        result = asyncio.run(self.service.execute_arm())

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "arm")
        self.assertEqual(self.drone.action.calls, ["arm"])

    def test_execute_takeoff_calls_altitude_then_takeoff(self):
        result = asyncio.run(self.service.execute_takeoff(12))

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "takeoff")
        self.assertEqual(
            self.drone.action.calls,
            [("set_takeoff_altitude", 12.0), "takeoff"],
        )

    def test_execute_set_takeoff_altitude_calls_mavsdk(self):
        result = asyncio.run(self.service.execute_set_takeoff_altitude(15))

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "set_takeoff_altitude")
        self.assertEqual(self.drone.action.calls, [("set_takeoff_altitude", 15.0)])

    def test_execute_set_flight_mode_maps_ardupilot_bypass(self):
        result = asyncio.run(self.service.execute_set_flight_mode("Q_HOVER"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "set_flight_mode")
        # Should NOT call action.hold() anymore, but send direct message
        self.assertEqual(self.drone.action.calls, [])
        self.assertEqual(len(self.drone.mavlink_direct.calls), 2)
        
        call_type, message = self.drone.mavlink_direct.calls[0]
        self.assertEqual(call_type, "send_message")
        self.assertEqual(message.message_name, "SET_MODE")
        
        import json
        fields = json.loads(message.fields_json)
        self.assertEqual(fields["custom_mode"], 18) # QHOVER

        _, command_long = self.drone.mavlink_direct.calls[1]
        self.assertEqual(command_long.message_name, "COMMAND_LONG")
        command_fields = json.loads(command_long.fields_json)
        self.assertEqual(command_fields["command"], 176)
        self.assertEqual(command_fields["param2"], 18.0)

    def test_execute_set_flight_mode_supports_qstabilize_bypass(self):
        # Previously rejected, now supported via bypass
        result = asyncio.run(self.service.execute_set_flight_mode("Q_STABILIZE"))
        self.assertTrue(result["ok"])
        
        call_type, message = self.drone.mavlink_direct.calls[0]
        import json
        fields = json.loads(message.fields_json)
        self.assertEqual(fields["custom_mode"], 17) # QSTABILIZE

    def test_execute_reboot_calls_mavsdk_reboot_when_disarmed(self):
        result = asyncio.run(self.service.execute_reboot())

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "reboot")
        self.assertEqual(self.drone.action.calls, ["reboot"])

    def test_execute_reboot_treats_disconnect_as_success(self):
        disconnecting_service = CommandService(self.state_manager, lambda: DisconnectingRebootDrone())

        result = asyncio.run(disconnecting_service.execute_reboot())

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "reboot")

    def test_execute_reboot_rejects_when_armed(self):
        self.state_manager.update(armed=True)

        with self.assertRaises(InvalidRequestError):
            asyncio.run(self.service.execute_reboot())

    def test_execute_arm_raises_when_drone_missing(self):
        service = CommandService(self.state_manager, lambda: None)

        with self.assertRaises(NotConnectedError):
            asyncio.run(service.execute_arm())

    def test_run_action_maps_asyncio_timeout_to_domain_timeout_error(self):
        with self.assertRaises(CommandTimeoutError):
            asyncio.run(self.service._run_action(asyncio.sleep(0.05), timeout=0.001))


if __name__ == "__main__":
    unittest.main()
