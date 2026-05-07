"""
Configuration: environment variables, constants, timeouts.
"""
import os

MAVSDK_ADDRESS = os.getenv("MAVSDK_ADDRESS", "serial://COM10:115200")
API_PORT = int(os.getenv("API_PORT", "5001"))
CONNECT_TIMEOUT_SECONDS = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "8"))
CONNECT_CALL_TIMEOUT_SECONDS = float(os.getenv("CONNECT_CALL_TIMEOUT_SECONDS", "5"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
