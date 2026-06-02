import threading
from collections import deque
from time import time as _time
from app.models import TelemetryState, PreArmHealth
from dataclasses import replace


_MAX_STATUS_TEXT_HISTORY = 20


class StateManager:
    
    def __init__(self):
        self._lock = threading.Lock()
        self._state = TelemetryState()
        self._prearm_health = PreArmHealth()
        self._status_text_history: deque[dict] = deque(maxlen=_MAX_STATUS_TEXT_HISTORY)
    
    def update(self, **kwargs):
        with self._lock:
            self._state = replace(self._state, **kwargs)
    
    def get(self) -> TelemetryState:
        with self._lock:
            return replace(self._state)

    # -- Pre-arm health -------------------------------------------------

    def update_prearm_health(self, **kwargs):
        with self._lock:
            self._prearm_health = replace(self._prearm_health, **kwargs)

    def get_prearm_health(self) -> PreArmHealth:
        with self._lock:
            return replace(self._prearm_health)

    # -- Status text ring buffer ----------------------------------------

    def append_status_text(self, text: str, msg_type: str = "INFO"):
        """Append a STATUSTEXT entry to the ring buffer (max 20)."""
        entry = {"ts": _time(), "type": msg_type, "text": text}
        with self._lock:
            self._status_text_history.append(entry)

    def get_status_text_history(self) -> list[dict]:
        with self._lock:
            return list(self._status_text_history)

    def get_prearm_texts(self) -> list[dict]:
        """Return only status text entries that contain 'PreArm' (case-insensitive)."""
        with self._lock:
            return [e for e in self._status_text_history if "prearm" in e["text"].lower()]
