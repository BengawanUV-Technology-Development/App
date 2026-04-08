"""
Command service: arm, disarm, takeoff, land, mission dengan preflight check.
Ini yang baru akan kita implement untuk MVP command layer.
"""
# TODO: Implement command execution with preflight validation
from time import time
from typing import Any
import uuid
from app.models import CommandResponse
from app.utils.state import StateManager
from app.validators import CommandValidator

class CommandService:
    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self.validator = CommandValidator(state_manager)

    def execute_arm(self):
        self.validator.validate_is_connected()
        #Panggil MAVSDK arm command di sini
        print("Execute arm command for drone")
        return self._build_success_payload("arm", "Vehicle armed successfully")
    
    def execute_disarm(self):
        self.validator.validate_is_connected()
        #Panggil MAVSDK disarm command di sini
        print("Execute disarm command for drone")
        return self._build_success_payload("disarm", "Vehicle disarmed successfully")
    
    def execute_takeoff(self, altitude_m: Any) -> dict:
        validated_alt = self.validator.validate_takeoff_request(altitude_m)
        #Panggil MAVSDK takeoff command dengan validated_alt di sini
        print(f"Execute takeoff command for drone with altitude {validated_alt} m")
        return self._build_success_payload("takeoff", f"Takeoff initiated to {validated_alt} meters")
    
    def execute_land(self):
        self.validator.validate_is_connected()
        #Panggil MAVSDK land command di sini
        print("Execute land command for drone")
        return self._build_success_payload("land", "Landing initiated")
    
    def execute_set_takeoff_altitude(self, altitude_m: Any) -> dict:
        validated_alt = self.validator.validate_takeoff_request(altitude_m)
        #Panggil MAVSDK command untuk set takeoff altitude dengan validated_alt di sini
        print(f"Set takeoff altitude to {validated_alt} m for drone")
        return self._build_success_payload("set_takeoff_altitude", f"Takeoff altitude set to {validated_alt} meters")

    def _build_success_payload(self, command: str, message: str) -> dict:
        resp = CommandResponse(
            ok=True,
            command=command,
            command_id=str(uuid.uuid4()),
            ts=time(),
            message=message
        )
        return resp.to_dict()
