from time import time
from typing import Any
import uuid
import asyncio
from typing import Callable, Protocol

from mavsdk.action import ActionError
from app.models import CommandResponse
from app.utils.errors import NotConnectedError
from app.utils.state import StateManager
from app.validators import CommandValidator


class DroneActionProtocol(Protocol):
    async def arm(self) -> None: ...

    async def disarm(self) -> None: ...

    async def takeoff(self) -> None: ...

    async def land(self) -> None: ...

    async def set_takeoff_altitude(self, altitude: float) -> None: ...


class DroneProtocol(Protocol):
    @property
    def action(self) -> DroneActionProtocol: ...

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
            raise RuntimeError("Command execution timed out")

    async def execute_arm(self):
        self.validator.validate_is_connected()
        try: 
            await self._run_action(self.drone.action.arm())
            return self._build_success_payload("arm", "Vehicle armed successfully")
        except ActionError as e:
            raise RuntimeError(f"Failed to arm vehicle: {str(e)}")
    
    async def execute_disarm(self):
        self.validator.validate_is_connected()
        try:
            await self._run_action(self.drone.action.disarm())
            return self._build_success_payload("disarm", "Vehicle disarmed successfully")
        except ActionError as e:
            raise RuntimeError(f"Failed to disarm vehicle: {str(e)}")

    async def execute_takeoff(self, altitude_m: Any) -> dict:
        validated_alt = self.validator.validate_takeoff_request(altitude_m)
        try:
            await self._run_action(self.drone.action.set_takeoff_altitude(validated_alt))
            await self._run_action(self.drone.action.takeoff())
            return self._build_success_payload("takeoff", f"Takeoff initiated to {validated_alt} meters")
        except ActionError as e:
            raise RuntimeError(f"Failed to initiate takeoff: {str(e)}")
        
    async def execute_set_takeoff_altitude(self, altitude_m: Any) -> dict:
        validated_alt = self.validator.validate_takeoff_request(altitude_m)
        try:
            await self._run_action(self.drone.action.set_takeoff_altitude(validated_alt))
            return self._build_success_payload("set_takeoff_altitude", f"Takeoff altitude set to {validated_alt} meters")
        except ActionError as e:
            raise RuntimeError(f"Failed to set takeoff altitude: {str(e)}")
        
    async def execute_land(self):
        self.validator.validate_is_connected()
        try:
            await self._run_action(self.drone.action.land())
            return self._build_success_payload("land", "Landing initiated")
        except ActionError as e:
            raise RuntimeError(f"Failed to initiate landing: {str(e)}")

    def _build_success_payload(self, command: str, message: str) -> dict:
        resp = CommandResponse(
            ok=True,
            command=command,
            command_id=str(uuid.uuid4()),
            ts=time(),
            message=message
        )
        return resp.to_dict()