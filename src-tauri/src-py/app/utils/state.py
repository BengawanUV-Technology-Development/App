import threading
from app.models import TelemetryState
from dataclasses import replace


class StateManager:
    
    def __init__(self):
        self._lock = threading.Lock()
        self._state = TelemetryState()
    
    def update(self, **kwargs):
        with self._lock:
            self._state = replace(self._state, **kwargs)
    
    def get(self) -> TelemetryState:
        with self._lock:
            return replace(self._state)
