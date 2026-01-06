from __future__ import annotations
from dataclasses import dataclass
from threading import Lock


@dataclass
class ControlState:
    """
    Shared control plane.
    enabled=False means WavePunkOS is OFF (injector should release all buttons).
    """
    _enabled: bool = True
    _lock: Lock = Lock()

    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value

    def toggle(self) -> bool:
        with self._lock:
            self._enabled = not self._enabled
            return self._enabled
