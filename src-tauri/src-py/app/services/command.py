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
    def __init__(self, state_manager: StateManager, drone_getter: Callable[[], DroneProtocol | None], event_logger: Any | None = None):
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

    async def _run_action(self, coroutine, timeout=5.0):
        try:
            return await asyncio.wait_for(coroutine, timeout=timeout)
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

    async def execute_arm(self):
        try: 
            self.validator.validate_is_connected()
            await self._run_action(self.drone.action.arm())
            result = self._build_success_payload("arm", "Vehicle armed successfully")
            self._record_command("arm", True, message=result["message"])
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("arm", False, error=str(exc), error_code=self._error_code_for_exception(exc))
            raise
        except ActionError as e:
            error_message = f"Failed to arm vehicle: {str(e)}"
            self._record_command("arm", False, error=error_message, error_code="COMMAND_FAILED")
            raise CommandFailedError(error_message)
    
    async def execute_disarm(self):
        try:
            self.validator.validate_is_connected()
            await self._run_action(self.drone.action.disarm())
            result = self._build_success_payload("disarm", "Vehicle disarmed successfully")
            self._record_command("disarm", True, message=result["message"])
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("disarm", False, error=str(exc), error_code=self._error_code_for_exception(exc))
            raise
        except ActionError as e:
            error_message = f"Failed to disarm vehicle: {str(e)}"
            self._record_command("disarm", False, error=error_message, error_code="COMMAND_FAILED")
            raise CommandFailedError(error_message)

    async def execute_takeoff(self, altitude_m: Any) -> dict:
        try:
            validated_alt = self.validator.validate_takeoff_request(altitude_m)
            await self._run_action(self.drone.action.set_takeoff_altitude(validated_alt))
            await self._run_action(self.drone.action.takeoff())
            result = self._build_success_payload("takeoff", f"Takeoff initiated to {validated_alt} meters")
            self._record_command("takeoff", True, message=result["message"], altitude_m=validated_alt)
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("takeoff", False, error=str(exc), error_code=self._error_code_for_exception(exc), altitude_m=altitude_m)
            raise
        except ActionError as e:
            error_message = f"Failed to initiate takeoff: {str(e)}"
            self._record_command("takeoff", False, error=error_message, error_code="COMMAND_FAILED", altitude_m=altitude_m)
            raise CommandFailedError(error_message)
        
    async def execute_set_takeoff_altitude(self, altitude_m: Any) -> dict:
        try:
            validated_alt = self.validator.validate_takeoff_request(altitude_m)
            await self._run_action(self.drone.action.set_takeoff_altitude(validated_alt))
            result = self._build_success_payload("set_takeoff_altitude", f"Takeoff altitude set to {validated_alt} meters")
            self._record_command("set_takeoff_altitude", True, message=result["message"], altitude_m=validated_alt)
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("set_takeoff_altitude", False, error=str(exc), error_code=self._error_code_for_exception(exc), altitude_m=altitude_m)
            raise
        except ActionError as e:
            error_message = f"Failed to set takeoff altitude: {str(e)}"
            self._record_command("set_takeoff_altitude", False, error=error_message, error_code="COMMAND_FAILED", altitude_m=altitude_m)
            raise CommandFailedError(error_message)
        
    async def execute_land(self):
        try:
            self.validator.validate_is_connected()
            await self._run_action(self.drone.action.land())
            result = self._build_success_payload("land", "Landing initiated")
            self._record_command("land", True, message=result["message"])
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("land", False, error=str(exc), error_code=self._error_code_for_exception(exc))
            raise
        except ActionError as e:
            error_str = str(e)
            if "UNSUPPORTED" in error_str:
                 error_message = "Wahana menolak perintah land (Mungkin harus di udara atau menggunakan mode Q_LAND)."
            else:
                 error_message = f"Failed to initiate landing: {error_str}"
            self._record_command("land", False, error=error_message, error_code="COMMAND_FAILED")
            raise CommandFailedError(error_message)

    async def execute_set_flight_mode(self, flight_mode: Any) -> dict:
        action_label = "set_flight_mode"
        try:
            normalized_mode = self._normalize_flight_mode(flight_mode)
            self.validator.validate_is_connected()

            if normalized_mode == FlightModeCommand.Q_STABILIZE:
                raise InvalidRequestError(
                    "Mode Q_STABILIZE belum didukung oleh backend MAVSDK ini"
                )

            if normalized_mode == FlightModeCommand.FBWA:
                action_label = "transition_to_fixedwing"
                coroutine = self.drone.action.transition_to_fixedwing()
                message = "Flight mode transition requested: FBWA (Fixed Wing)"
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
                message = "Flight mode transition requested: AUTO / RTL"
            elif normalized_mode == FlightModeCommand.MANUAL:
                action_label = "manual"
                coroutine = self.drone.action.transition_to_multicopter()
                message = "Flight mode transition requested: MANUAL (Emergency recovery to Multicopter)"
            else:
                raise InvalidRequestError(
                    f"Mode {normalized_mode.value} belum didukung oleh backend MAVSDK ini"
                )

            await self._run_action(coroutine)
            result = self._build_success_payload("set_flight_mode", message)
            self._record_command("set_flight_mode", True, message=result["message"], requested_mode=normalized_mode.value, action_label=action_label)
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            requested_mode = flight_mode.value if isinstance(flight_mode, FlightModeCommand) else flight_mode
            self._record_command("set_flight_mode", False, error=str(exc), error_code=self._error_code_for_exception(exc), requested_mode=requested_mode)
            raise
        except ActionError as e:
            error_message = f"Failed to execute {action_label}: {str(e)}"
            if "NO_VTOL_TRANSITION_SUPPORT" in str(e):
                error_message = "Wahana tidak mem-broadcast kemampuan VTOL ke MAVSDK. Perintah transisi (FBWA/Q_STABILIZE) ditolak oleh FC."
            else:
                error_message = f"Gagal eksekusi {action_label}: {str(e)}"
            requested_mode = flight_mode.value if isinstance(flight_mode, FlightModeCommand) else flight_mode
            self._record_command("set_flight_mode", False, error=error_message, error_code="COMMAND_FAILED", requested_mode=requested_mode)
            raise CommandFailedError(error_message)

    async def execute_reboot(self) -> dict:
        self.validator.validate_is_connected()

        state = self.state_manager.get()
        if state.armed:
            error_message = "Reboot hanya boleh saat vehicle disarmed"
            self._record_command("reboot", False, error=error_message, error_code="INVALID_REQUEST")
            raise InvalidRequestError(error_message)

        try:
            print("[status] reboot requested")
            await self._run_action(self.drone.action.reboot())
            result = self._build_success_payload("reboot", "Reboot requested successfully")
            print("[status] reboot command sent")
            self._record_command("reboot", True, message=result["message"])
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            self._record_command("reboot", False, error=str(exc), error_code=self._error_code_for_exception(exc))
            raise
        except ActionError as e:
            error_message = f"Failed to execute reboot: {str(e)}"
            self._record_command("reboot", False, error=error_message, error_code="COMMAND_FAILED")
            raise CommandFailedError(error_message)

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