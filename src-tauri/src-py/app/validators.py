from typing import Any

from app.utils.state import StateManager
from app.utils.errors import NotConnectedError, InvalidRequestError


class CommandValidator:
    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
    
    def validate_is_connected(self) -> bool:
        state = self.state_manager.get()
        if not state.connected:
            raise NotConnectedError()
        return True

    def validate_is_armed(self) -> bool:
        state = self.state_manager.get()
        if not state.armed:
            raise InvalidRequestError("Vehicle harus ARM sebelum ganti flight mode")
        return True
    
    def validate_takeoff_request(self, altitude_m: Any) -> float:
        try:
            val = float(altitude_m)
        except (ValueError, TypeError):
            raise InvalidRequestError(f"Altitude harus angka, dapat {altitude_m}")

        if val < 2 or val > 50:
            raise InvalidRequestError(f"Altitude harus 2-50 meter, dapat {val}")
        
        self.validate_is_connected()
        return val
    