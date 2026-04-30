"""
Error codes dan custom exceptions untuk consistent error handling.
"""
from enum import Enum


class ErrorCode(str, Enum):
    """Standard error codes"""
    NOT_CONNECTED = "NOT_CONNECTED"
    BUSY = "BUSY"
    INVALID_REQUEST = "INVALID_REQUEST"
    COMMAND_FAILED = "COMMAND_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    TIMEOUT = "TIMEOUT"


class GroundStationError(Exception):
    """Base exception"""
    def __init__(self, error_code: ErrorCode, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class NotConnectedError(GroundStationError):
    """Vehicle tidak connected"""
    def __init__(self, message: str = "Vehicle is not connected"):
        super().__init__(ErrorCode.NOT_CONNECTED, message)


class CommandFailedError(GroundStationError):
    """Command execution gagal"""
    def __init__(self, message: str):
        super().__init__(ErrorCode.COMMAND_FAILED, message)


class CommandTimeoutError(GroundStationError):
    """Command execution timeout"""
    def __init__(self, message: str = "Command execution timed out"):
        super().__init__(ErrorCode.TIMEOUT, message)


class InvalidRequestError(GroundStationError):
    """Request body invalid"""
    def __init__(self, message: str):
        super().__init__(ErrorCode.INVALID_REQUEST, message)
