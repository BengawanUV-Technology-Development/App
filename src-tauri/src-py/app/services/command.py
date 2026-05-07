from time import time
from enum import Enum
from typing import Any
import uuid
import asyncio
import json
import logging
from typing import Callable, Protocol

from mavsdk.action import ActionError
from mavsdk.telemetry import FlightMode as MavsdkFlightMode
from mavsdk.mavlink_direct import MavlinkMessage
from app.models import CommandResponse
from app.utils.errors import CommandFailedError, CommandTimeoutError, InvalidRequestError, NotConnectedError
from app.utils.state import StateManager
from app.validators import CommandValidator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ArduPilot Direct Mode Bypass
# ---------------------------------------------------------------------------
# Maps human-readable ArduPilot QuadPlane mode names to their integer IDs.
# Used to send SET_MODE (#11) via mavlink_direct, bypassing
# MAVSDK's strict PX4-centric Action plugin validation.
# Reference: https://ardupilot.org/plane/docs/parameters.html#fltmode1
# ---------------------------------------------------------------------------
ARDUPILOT_MODE_MAPPING: dict[str, int] = {
    "MANUAL":     0,
    "FBWA":       5,
    "AUTO":       10,
    "RTL":        11,
    "QSTABILIZE": 17,
    "QHOVER":     18,
    "QLAND":      20,
}

# MAV_MODE_FLAG_CUSTOM_MODE_ENABLED  (decimal 1, bit 0)
_MAV_MODE_FLAG_CUSTOM = 1
# Default target identifiers (single-vehicle setup)
_DEFAULT_TARGET_SYSID = 1
_DEFAULT_TARGET_COMPID = 1


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


class DroneMavlinkDirectProtocol(Protocol):
    async def send_message(self, message: MavlinkMessage) -> None: ...


class DroneProtocol(Protocol):
    @property
    def action(self) -> DroneActionProtocol: ...

    @property
    def mavlink_direct(self) -> DroneMavlinkDirectProtocol: ...


class FlightModeCommand(str, Enum):
    FBWA = "FBWA"
    Q_STABILIZE = "Q_STABILIZE"
    Q_HOVER = "Q_HOVER"
    Q_LAND = "Q_LAND"
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    RTL = "RTL"
    QSTABILIZE = "QSTABILIZE"
    QHOVER = "QHOVER"
    QLAND = "QLAND"

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

    async def _execute_ardupilot_mode_direct(self, mode_name: str, custom_mode_id: int) -> None:
        """Send SET_MODE (#11) via mavlink_direct.

        This bypasses MAVSDK's Action plugin validation which incorrectly
        rejects ArduPilot VTOL transitions with UNSUPPORTED /
        VTOL_TRANSITION_SUPPORT_UNKNOWN errors.
        """
        fields = {
            "target_system": _DEFAULT_TARGET_SYSID,
            "base_mode": _MAV_MODE_FLAG_CUSTOM,
            "custom_mode": custom_mode_id
        }

        message = MavlinkMessage(
            message_name="SET_MODE",
            system_id=0, # MAVSDK will override if needed, or 0 for local
            component_id=0,
            target_system_id=_DEFAULT_TARGET_SYSID,
            target_component_id=_DEFAULT_TARGET_COMPID,
            fields_json=json.dumps(fields)
        )

        logger.info(
            "ardupilot_direct_mode mode=%s custom_mode_id=%d",
            mode_name,
            custom_mode_id,
        )
        await self.drone.mavlink_direct.send_message(message)

    async def execute_set_flight_mode(self, flight_mode: Any) -> dict:
        action_label = "set_flight_mode"
        try:
            normalized_mode = self._normalize_flight_mode(flight_mode)
            self.validator.validate_is_connected()

            # --- ArduPilot Direct Bypass ---
            # Resolve the canonical ArduPilot mode key for the mapping lookup.
            ardupilot_key = self._resolve_ardupilot_key(normalized_mode)

            if ardupilot_key and ardupilot_key in ARDUPILOT_MODE_MAPPING:
                custom_mode_id = ARDUPILOT_MODE_MAPPING[ardupilot_key]
                action_label = f"direct_set_mode_{ardupilot_key}"

                try:
                    await self._run_action(
                        self._execute_ardupilot_mode_direct(ardupilot_key, custom_mode_id),
                        timeout=5.0,
                    )
                except Exception as direct_exc:
                    error_message = (
                        f"ArduPilot direct mode switch gagal untuk {ardupilot_key} "
                        f"(custom_mode={custom_mode_id}): {direct_exc}"
                    )
                    logger.warning("ardupilot_direct_mode_failed mode=%s error=%s", ardupilot_key, direct_exc)
                    self._record_command(
                        "set_flight_mode", False,
                        error=error_message, error_code="COMMAND_FAILED",
                        requested_mode=normalized_mode.value,
                        action_label=action_label,
                        method="direct",
                    )
                    raise CommandFailedError(error_message)

                message = f"Flight mode set via ArduPilot direct bypass: {ardupilot_key}"
                result = self._build_success_payload("set_flight_mode", message)
                self._record_command(
                    "set_flight_mode", True,
                    message=result["message"],
                    requested_mode=normalized_mode.value,
                    action_label=action_label,
                    method="direct",
                )
                return result

            # --- Standard MAVSDK Action Fallback ---
            # Modes not in the ArduPilot mapping go through MAVSDK's Action plugin.
            if normalized_mode == FlightModeCommand.FBWA:
                action_label = "transition_to_fixedwing"
                coroutine = self.drone.action.transition_to_fixedwing()
                message = "Flight mode transition requested: FBWA (Fixed Wing)"
            elif normalized_mode in (FlightModeCommand.Q_HOVER, FlightModeCommand.QHOVER):
                action_label = "hold"
                coroutine = self.drone.action.hold()
                message = "Flight mode transition requested: Q_HOVER / hold"
            elif normalized_mode in (FlightModeCommand.Q_LAND, FlightModeCommand.QLAND):
                action_label = "land"
                coroutine = self.drone.action.land()
                message = "Flight mode transition requested: Q_LAND / land"
            elif normalized_mode == FlightModeCommand.AUTO:
                action_label = "return_to_launch"
                coroutine = self.drone.action.return_to_launch()
                message = "Flight mode transition requested: AUTO / RTL"
            elif normalized_mode == FlightModeCommand.RTL:
                action_label = "return_to_launch"
                coroutine = self.drone.action.return_to_launch()
                message = "Flight mode transition requested: RTL"
            elif normalized_mode == FlightModeCommand.MANUAL:
                action_label = "manual"
                coroutine = self.drone.action.transition_to_multicopter()
                message = "Flight mode transition requested: MANUAL (Emergency recovery to Multicopter)"
            else:
                raise InvalidRequestError(
                    f"Mode {normalized_mode.value} belum didukung oleh backend ini"
                )

            await self._run_action(coroutine)
            result = self._build_success_payload("set_flight_mode", message)
            self._record_command("set_flight_mode", True, message=result["message"], requested_mode=normalized_mode.value, action_label=action_label, method="mavsdk_action")
            return result
        except (NotConnectedError, InvalidRequestError, CommandTimeoutError) as exc:
            requested_mode = flight_mode.value if isinstance(flight_mode, FlightModeCommand) else flight_mode
            self._record_command("set_flight_mode", False, error=str(exc), error_code=self._error_code_for_exception(exc), requested_mode=requested_mode)
            raise
        except CommandFailedError:
            raise  # Already recorded above
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
            self.state_manager.update(status="REBOOTING", error=None, last_update=time())
            print("[status] reboot requested")
            try:
                await asyncio.wait_for(self.drone.action.reboot(), timeout=2.0)
            except asyncio.TimeoutError:
                print("[status] reboot command acknowledged, not waiting for FC restart")
            except Exception as exc:
                if self._is_expected_reboot_disconnect(exc):
                    print(f"[status] reboot command sent, link reset as expected: {exc}")
                else:
                    raise

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

    def _is_expected_reboot_disconnect(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "unavailable" in message
            or "connection reset" in message
            or "forcibly closed by the remote host" in message
            or "wsagetoverlappedresult" in message
        )

    # Maps alternative / legacy name forms to canonical FlightModeCommand values.
    _MODE_ALIASES: dict[str, str] = {
        "Q_STABILIZE": "QSTABILIZE",
        "Q_HOVER":     "QHOVER",
        "Q_LAND":      "QLAND",
    }

    def _normalize_flight_mode(self, flight_mode: Any) -> FlightModeCommand:
        if isinstance(flight_mode, FlightModeCommand):
            return flight_mode

        if not isinstance(flight_mode, str):
            raise InvalidRequestError("Mode harus string")

        normalized = flight_mode.strip().upper()

        # Resolve known aliases so both "Q_STABILIZE" and "QSTABILIZE" work.
        normalized = self._MODE_ALIASES.get(normalized, normalized)

        try:
            return FlightModeCommand(normalized)
        except ValueError as exc:
            valid = ", ".join(m.value for m in FlightModeCommand)
            raise InvalidRequestError(
                f"Mode tidak dikenali. Pilihan valid: {valid}"
            ) from exc

    @staticmethod
    def _resolve_ardupilot_key(mode: FlightModeCommand) -> str | None:
        """Return the ARDUPILOT_MODE_MAPPING key for a FlightModeCommand,
        or None if the mode should fall through to standard MAVSDK actions."""
        _ENUM_TO_AP_KEY: dict[FlightModeCommand, str] = {
            FlightModeCommand.MANUAL:      "MANUAL",
            FlightModeCommand.FBWA:        "FBWA",
            FlightModeCommand.AUTO:        "AUTO",
            FlightModeCommand.RTL:         "RTL",
            FlightModeCommand.Q_STABILIZE: "QSTABILIZE",
            FlightModeCommand.QSTABILIZE:  "QSTABILIZE",
            FlightModeCommand.Q_HOVER:     "QHOVER",
            FlightModeCommand.QHOVER:      "QHOVER",
            FlightModeCommand.Q_LAND:      "QLAND",
            FlightModeCommand.QLAND:       "QLAND",
        }
        return _ENUM_TO_AP_KEY.get(mode)

    def _build_success_payload(self, command: str, message: str) -> dict:
        resp = CommandResponse(
            ok=True,
            command=command,
            command_id=str(uuid.uuid4()),
            ts=time(),
            message=message
        )
        return resp.to_dict()