"""
Command service: arm, disarm, takeoff, land, mission dengan preflight check.
Ini yang baru akan kita implement untuk MVP command layer.
"""
# TODO: Implement command execution with preflight validation
from time import time
from typing import Any
import uuid, asyncio
from mavsdk import System
from mavsdk.action import ActionError 
from app.models import CommandResponse
from app.utils.state import StateManager
from app.validators import CommandValidator

class CommandService:
    def __init__(self, state_manager: StateManager, drone: System):
        self.state_manager = state_manager
        self.drone = drone
        self.validator = CommandValidator(state_manager)

    async def _run_action(self, coroutine, timeout=5.0):
        try:
            return await asyncio.wait_for(coroutine, timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError("Command execution timed out")
        except ActionError as e:
            raise RuntimeError(f"Command execution failed: {str(e)}")

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
            await self._run_action(self.drone.action.takeoff())
            return self._build_success_payload("takeoff", f"Takeoff initiated to {validated_alt} meters")
        except ActionError as e:
            raise RuntimeError(f"Failed to initiate takeoff: {str(e)}")
    
    async def execute_land(self):
        self.validator.validate_is_connected()
        try:
            await self._run_action(self.drone.action.land())
            return self._build_success_payload("land", "Landing initiated")
        except ActionError as e:
            raise RuntimeError(f"Failed to initiate landing: {str(e)}")
    
    async def execute_set_takeoff_altitude(self, altitude_m: Any) -> dict:
        validated_alt = self.validator.validate_takeoff_request(altitude_m)
        try:
            await self._run_action(self.drone.action.set_takeoff_altitude(altitude_m))
            return self._build_success_payload("set_takeoff_altitude", f"Takeoff altitude set to {validated_alt} meters")
        except ActionError as e:
            raise RuntimeError(f"Failed to set takeoff altitude: {str(e)}")

    def _build_success_payload(self, command: str, message: str) -> dict:
        resp = CommandResponse(
            ok=True,
            command=command,
            command_id=str(uuid.uuid4()),
            ts=time(),
            message=message
        )
        return resp.to_dict()
