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

    async def set_takeoff_altitude(self, altitude):
        self.calls.append(("set_takeoff_altitude", altitude))


class FakeDrone:
    def __init__(self):
        self._action = FakeAction()

    @property
    def action(self):
        return self._action


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

    def test_execute_arm_raises_when_drone_missing(self):
        service = CommandService(self.state_manager, lambda: None)

        with self.assertRaises(NotConnectedError):
            asyncio.run(service.execute_arm())

    def test_run_action_maps_asyncio_timeout_to_domain_timeout_error(self):
        with self.assertRaises(CommandTimeoutError):
            asyncio.run(self.service._run_action(asyncio.sleep(0.05), timeout=0.001))


if __name__ == "__main__":
    unittest.main()
