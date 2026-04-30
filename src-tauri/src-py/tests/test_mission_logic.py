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

from app.services.mission import MissionService
from app.utils.errors import InvalidRequestError
from app.utils.state import StateManager


class FakeMission:
    def __init__(self):
        self.calls = []

    def upload_mission(self, mission_plan):
        self.calls.append(("upload_mission", len(mission_plan.mission_items)))
        return "success"

    def start_mission(self):
        self.calls.append("start_mission")
        return "success"

    def pause_mission(self):
        self.calls.append("pause_mission")
        return "success"

    def clear_mission(self):
        self.calls.append("clear_mission")
        return "success"

    def mission_progress(self):
        self.calls.append("mission_progress")

        class Progress:
            current = 2
            total = 5

        return Progress()


class FakeDrone:
    def __init__(self):
        self.mission = FakeMission()


class MissionServiceTests(unittest.TestCase):
    def setUp(self):
        self.state_manager = StateManager()
        self.state_manager.update(connected=True)
        self.drone = FakeDrone()
        self.service = MissionService(self.state_manager, lambda: self.drone)

    def test_execute_upload_mission_builds_plan_and_calls_mavsdk(self):
        result = asyncio.run(
            self.service.execute_upload_mission(
                [
                    {
                        "seq": 0,
                        "latitude_deg": -6.2,
                        "longitude_deg": 106.8,
                        "relative_altitude_m": 10,
                    },
                    {
                        "seq": 1,
                        "latitude_deg": -6.2001,
                        "longitude_deg": 106.8001,
                        "relative_altitude_m": 12,
                    },
                ]
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "mission_upload")
        self.assertEqual(self.drone.mission.calls[0], ("upload_mission", 2))

    def test_execute_upload_mission_rejects_invalid_waypoint_range(self):
        with self.assertRaises(InvalidRequestError):
            asyncio.run(
                self.service.execute_upload_mission(
                    [
                        {
                            "seq": 0,
                            "latitude_deg": 120,
                            "longitude_deg": 106.8,
                            "relative_altitude_m": 10,
                        }
                    ]
                )
            )

    def test_execute_mission_progress_returns_progress_values(self):
        result = asyncio.run(self.service.execute_mission_progress())

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "mission_progress")
        self.assertEqual(result["current"], 2)
        self.assertEqual(result["total"], 5)


if __name__ == "__main__":
    unittest.main()