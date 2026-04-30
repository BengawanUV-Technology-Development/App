from time import time
from enum import Enum
from typing import Any
import uuid
import asyncio
from typing import Callable, Protocol

from mavsdk.action import ActionError
from mavsdk.telemetry import FlightMode as MavsdkFlightMode
from app.models import CommandResponse
from app.utils.errors import CommandFailedError, CommandTimeoutError, InvalidRequestError, NotConnectedError
from app.utils.state import StateManager
from app.validators import CommandValidator


class DroneActionProtocol(Protocol):
    async def arm(self) -> None: ...

    async def disarm(self) -> None: ...

    async def takeoff(self) -> None: ...

    async def land(self) -> None: ...

    async def hold(self) -> None: ...

    async def return_to_launch(self) -> None: ...

    async def transition_to_fixedwing(self) -> None: ...

    async def transition_to_multicopter(self) -> None: ...

    async def reboot(self) -> None: ...

    async def set_takeoff_altitude(self, altitude: float) -> None: ...


class DroneProtocol(Protocol):
    @property
    def action(self) -> DroneActionProtocol: ...


class FlightModeCommand(str, Enum):
    FBWA = "FBWA"
    Q_STABILIZE = "Q_STABILIZE"
    Q_HOVER = "Q_HOVER"
    Q_LAND = "Q_LAND"
    AUTO = "AUTO"
    MANUAL = "MANUAL"

class CommandService:
    def __init__(self, state_manager: StateManager, drone_getter: Callable[[], DroneProtocol | None]):
        self.state_manager = state_manager
        self.drone_getter = drone_getter
        self.validator = CommandValidator(state_manager)

    @property
    def drone(self):
        current_drone = self.drone_getter()
        if current_drone is None:
            raise NotConnectedError("Vehicle is not connected")
        return current_drone

    async def _run_action(self, coroutine, timeout=5.0):
        try:
            return await asyncio.wait_for(coroutine, timeout=timeout)
        except asyncio.TimeoutError:
            raise CommandTimeoutError()

    async def execute_arm(self):
        self.validator.validate_is_connected()
        try: 
            await self._run_action(self.drone.action.arm())
            return self._build_success_payload("arm", "Vehicle armed successfully")
        except ActionError as e:
            raise CommandFailedError(f"Failed to arm vehicle: {str(e)}")
    
    async def execute_disarm(self):
        self.validator.validate_is_connected()
        try:
            await self._run_action(self.drone.action.disarm())
            return self._build_success_payload("disarm", "Vehicle disarmed successfully")
        except ActionError as e:
            raise CommandFailedError(f"Failed to disarm vehicle: {str(e)}")

    async def execute_takeoff(self, altitude_m: Any) -> dict:
        validated_alt = self.validator.validate_takeoff_request(altitude_m)
        try:
            await self._run_action(self.drone.action.set_takeoff_altitude(validated_alt))
            await self._run_action(self.drone.action.takeoff())
            return self._build_success_payload("takeoff", f"Takeoff initiated to {validated_alt} meters")
        except ActionError as e:
            raise CommandFailedError(f"Failed to initiate takeoff: {str(e)}")
        
    async def execute_set_takeoff_altitude(self, altitude_m: Any) -> dict:
        validated_alt = self.validator.validate_takeoff_request(altitude_m)
        try:
            await self._run_action(self.drone.action.set_takeoff_altitude(validated_alt))
            return self._build_success_payload("set_takeoff_altitude", f"Takeoff altitude set to {validated_alt} meters")
        except ActionError as e:
            raise CommandFailedError(f"Failed to set takeoff altitude: {str(e)}")
        
    async def execute_land(self):
        self.validator.validate_is_connected()
        try:
            await self._run_action(self.drone.action.land())
            return self._build_success_payload("land", "Landing initiated")
        except ActionError as e:
            raise CommandFailedError(f"Failed to initiate landing: {str(e)}")

    async def execute_set_flight_mode(self, flight_mode: Any) -> dict:
        normalized_mode = self._normalize_flight_mode(flight_mode)
        self.validator.validate_is_connected()

        if normalized_mode == FlightModeCommand.FBWA:
            action_label = "transition_to_fixedwing"
            coroutine = self.drone.action.transition_to_fixedwing()
            message = "Flight mode transition requested: FBWA / fixed wing"
        elif normalized_mode == FlightModeCommand.Q_HOVER:
            action_label = "hold"
            coroutine = self.drone.action.hold()
            message = "Flight mode transition requested: Q_HOVER / hold"
        elif normalized_mode == FlightModeCommand.Q_LAND:
            action_label = "land"
            coroutine = self.drone.action.land()
            message = "Flight mode transition requested: Q_LAND / land"
        elif normalized_mode == FlightModeCommand.AUTO:
            action_label = "return_to_launch"
            coroutine = self.drone.action.return_to_launch()
            message = "Flight mode transition requested: AUTO / return to launch"
        elif normalized_mode == FlightModeCommand.MANUAL:
            action_label = "transition_to_multicopter"
            coroutine = self.drone.action.transition_to_multicopter()
            message = "Flight mode transition requested: MANUAL / multicopter"
        else:
            raise InvalidRequestError(
                f"Mode {normalized_mode.value} belum didukung oleh backend MAVSDK ini"
            )

        try:
            await self._run_action(coroutine)
            return self._build_success_payload("set_flight_mode", message)
        except ActionError as e:
            raise CommandFailedError(f"Failed to execute {action_label}: {str(e)}")

    async def execute_reboot(self) -> dict:
        self.validator.validate_is_connected()

        state = self.state_manager.get()
        if state.armed:
            raise InvalidRequestError("Reboot hanya boleh saat vehicle disarmed")

        try:
            await self._run_action(self.drone.action.reboot())
            return self._build_success_payload("reboot", "Reboot requested successfully")
        except ActionError as e:
            raise CommandFailedError(f"Failed to execute reboot: {str(e)}")

    def _normalize_flight_mode(self, flight_mode: Any) -> FlightModeCommand:
        if isinstance(flight_mode, FlightModeCommand):
            return flight_mode

        if not isinstance(flight_mode, str):
            raise InvalidRequestError("Mode harus string")

        normalized = flight_mode.strip().upper()
        try:
            return FlightModeCommand(normalized)
        except ValueError as exc:
            raise InvalidRequestError(
                "Mode harus salah satu dari FBWA, Q_STABILIZE, Q_HOVER, Q_LAND, AUTO, MANUAL"
            ) from exc

    def _build_success_payload(self, command: str, message: str) -> dict:
        resp = CommandResponse(
            ok=True,
            command=command,
            command_id=str(uuid.uuid4()),
            ts=time(),
            message=message
        )
        return resp.to_dict()