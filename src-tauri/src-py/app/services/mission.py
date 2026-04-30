from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import time
from typing import Any, Callable, Protocol
import asyncio
import uuid

from app.models import CommandResponse
from app.utils.errors import CommandFailedError, CommandTimeoutError, InvalidRequestError, NotConnectedError
from app.utils.state import StateManager
from app.validators import CommandValidator
from mavsdk.mission import MissionItem, MissionPlan


class MissionItemProtocol(Protocol):
    async def __call__(self) -> None: ...


class DroneMissionProtocol(Protocol):
    @property
    def mission(self) -> Any: ...


class MissionWaypointPayload(dict):
    pass


class MissionService:
    def __init__(self, state_manager: StateManager, drone_getter: Callable[[], Any | None], event_logger: Any | None = None):
        self.state_manager = state_manager
        self.drone_getter = drone_getter
        self.validator = CommandValidator(state_manager)
        self.event_logger = event_logger

    @property
    def drone(self):
        current_drone = self.drone_getter()
        if current_drone is None:
            raise NotConnectedError("Vehicle is not connected")
        return current_drone

    def _get_mission_plugin(self) -> Any:
        return self.drone.mission

    async def _run_blocking(self, func, timeout: float = 10.0):
        try:
            return await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout)
        except asyncio.TimeoutError:
            raise CommandTimeoutError()

    def _record_command(self, command: str, ok: bool, message: str | None = None, error: str | None = None, error_code: str | None = None, **data: Any):
        if self.event_logger is not None:
            self.event_logger.record_command(command, ok, message=message, error=error, error_code=error_code, **data)

    def _error_code_for_exception(self, exc: Exception) -> str:
        if isinstance(exc, NotConnectedError):
            return "NOT_CONNECTED"
        if isinstance(exc, InvalidRequestError):
            return "INVALID_REQUEST"
        if isinstance(exc, CommandTimeoutError):
            return "TIMEOUT"
        return "COMMAND_FAILED"

    def _build_mission_plan(self, waypoints: list[dict[str, Any]]) -> MissionPlan:
        if not isinstance(waypoints, list) or not waypoints:
            raise InvalidRequestError("Waypoints tidak boleh kosong")

        mission_items: list[MissionItem] = []
        seen_sequences: set[int] = set()

        for index, waypoint in enumerate(waypoints):
            if not isinstance(waypoint, dict):
                raise InvalidRequestError(f"Waypoint #{index} harus berupa object")

            latitude = self._coerce_float(waypoint.get("latitude_deg"), "latitude_deg")
            longitude = self._coerce_float(waypoint.get("longitude_deg"), "longitude_deg")
            altitude = self._coerce_float(waypoint.get("relative_altitude_m"), "relative_altitude_m")
            speed = self._coerce_float(waypoint.get("speed_m_s", 5.0), "speed_m_s")
            is_fly_through = bool(waypoint.get("is_fly_through", False))
            sequence = waypoint.get("seq", index)

            if not isinstance(sequence, int):
                raise InvalidRequestError(f"seq waypoint #{index} harus integer")
            if sequence in seen_sequences:
                raise InvalidRequestError(f"seq waypoint duplikat: {sequence}")
            seen_sequences.add(sequence)

            if latitude < -90 or latitude > 90:
                raise InvalidRequestError(f"latitude_deg harus di antara -90 dan 90, dapat {latitude}")
            if longitude < -180 or longitude > 180:
                raise InvalidRequestError(f"longitude_deg harus di antara -180 dan 180, dapat {longitude}")

            mission_item = MissionItem(
                latitude,
                longitude,
                altitude,
                speed,
                is_fly_through,
                float(waypoint.get("gimbal_pitch_deg", 0.0)),
                float(waypoint.get("gimbal_yaw_deg", 0.0)),
                MissionItem.CameraAction.NONE,
                float(waypoint.get("loiter_time_s", 0.0)),
                float(waypoint.get("camera_photo_interval_s", 1.0)),
                float(waypoint.get("acceptance_radius_m", 1.0)),
                float(waypoint.get("yaw_deg", 0.0)),
                float(waypoint.get("camera_photo_distance_m", 0.0)),
                MissionItem.VehicleAction.NONE,
            )
            mission_items.append(mission_item)

        return MissionPlan(mission_items)

    def _coerce_float(self, value: Any, field_name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise InvalidRequestError(f"{field_name} harus angka") from exc

    async def execute_upload_mission(self, waypoints: list[dict[str, Any]]) -> dict:
        try:
            self.validator.validate_is_connected()
            mission_plan = self._build_mission_plan(waypoints)
            mission = self._get_mission_plugin()

            await self._run_blocking(lambda: mission.upload_mission(mission_plan), timeout=20.0)
            result = self._build_success_payload(
                "mission_upload",
                f"Mission uploaded with {len(mission_plan.mission_items)} waypoints",
            )
            self._record_command("mission_upload", True, message=result["message"], waypoint_count=len(mission_plan.mission_items))
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("mission_upload", False, error=str(exc), error_code=self._error_code_for_exception(exc))
            raise
        except Exception as exc:
            error_message = f"Failed to upload mission: {exc}"
            self._record_command("mission_upload", False, error=error_message, error_code="COMMAND_FAILED")
            raise CommandFailedError(error_message) from exc

    async def execute_start_mission(self) -> dict:
        try:
            self.validator.validate_is_connected()
            mission = self._get_mission_plugin()
            await self._run_blocking(lambda: mission.start_mission(), timeout=10.0)
            result = self._build_success_payload("mission_start", "Mission start requested")
            self._record_command("mission_start", True, message=result["message"])
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("mission_start", False, error=str(exc), error_code=self._error_code_for_exception(exc))
            raise
        except Exception as exc:
            error_message = f"Failed to start mission: {exc}"
            self._record_command("mission_start", False, error=error_message, error_code="COMMAND_FAILED")
            raise CommandFailedError(error_message) from exc

    async def execute_pause_mission(self) -> dict:
        try:
            self.validator.validate_is_connected()
            mission = self._get_mission_plugin()
            await self._run_blocking(lambda: mission.pause_mission(), timeout=10.0)
            result = self._build_success_payload("mission_pause", "Mission pause requested")
            self._record_command("mission_pause", True, message=result["message"])
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("mission_pause", False, error=str(exc), error_code=self._error_code_for_exception(exc))
            raise
        except Exception as exc:
            error_message = f"Failed to pause mission: {exc}"
            self._record_command("mission_pause", False, error=error_message, error_code="COMMAND_FAILED")
            raise CommandFailedError(error_message) from exc

    async def execute_clear_mission(self) -> dict:
        try:
            self.validator.validate_is_connected()
            mission = self._get_mission_plugin()
            await self._run_blocking(lambda: mission.clear_mission(), timeout=10.0)
            result = self._build_success_payload("mission_clear", "Mission clear requested")
            self._record_command("mission_clear", True, message=result["message"])
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("mission_clear", False, error=str(exc), error_code=self._error_code_for_exception(exc))
            raise
        except Exception as exc:
            error_message = f"Failed to clear mission: {exc}"
            self._record_command("mission_clear", False, error=error_message, error_code="COMMAND_FAILED")
            raise CommandFailedError(error_message) from exc

    async def execute_mission_progress(self) -> dict:
        try:
            self.validator.validate_is_connected()
            mission = self._get_mission_plugin()
            progress = await self._run_blocking(lambda: mission.mission_progress(), timeout=10.0)
            result = {
                "ok": True,
                "command": "mission_progress",
                "command_id": str(uuid.uuid4()),
                "ts": time(),
                "current": getattr(progress, "current", None),
                "total": getattr(progress, "total", None),
            }
            self._record_command(
                "mission_progress",
                True,
                message="Mission progress read",
                current=result["current"],
                total=result["total"],
            )
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("mission_progress", False, error=str(exc), error_code=self._error_code_for_exception(exc))
            raise
        except Exception as exc:
            error_message = f"Failed to get mission progress: {exc}"
            self._record_command("mission_progress", False, error=error_message, error_code="COMMAND_FAILED")
            raise CommandFailedError(error_message) from exc

    def _build_success_payload(self, command: str, message: str) -> dict:
        resp = CommandResponse(
            ok=True,
            command=command,
            command_id=str(uuid.uuid4()),
            ts=time(),
            message=message,
        )
        return resp.to_dict()