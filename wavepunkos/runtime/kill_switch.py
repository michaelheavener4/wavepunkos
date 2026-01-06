from __future__ import annotations

from dataclasses import dataclass
import time

from wavepunkos.core.control import ControlState
from wavepunkos.core.types import InputEvent, EventType, MouseButton, ButtonAction
from wavepunkos.interpreter.state_machine import Interpreter
from wavepunkos.injector.uinput_mouse import UInputMouse


@dataclass
class KillSwitch:
    """
    Central safety gate.
    If ControlState is OFF, we:
      - force interpreter OFF
      - release buttons
      - block all injection
    """
    state: ControlState
    interp: Interpreter
    mouse: UInputMouse

    _last_enabled: bool = True
    _left_is_down: bool = False
    _left_down_t: float | None = None

    def guard(self, t_ms: int) -> None:
        enabled = self.state.is_enabled()
        if enabled == self._last_enabled:
            return

        self._last_enabled = enabled

        if not enabled:
            # Transition -> OFF: hard stop
            self.interp.set_off(True, t_ms=t_ms)
            self._release_all()
        else:
            # Transition -> ON: clear OFF state
            self.interp.set_off(False, t_ms=t_ms)

    def allow(self) -> bool:
        return self.state.is_enabled()

    def apply(self, ev: InputEvent) -> None:
        """
        Apply an InputEvent to the OS ONLY if enabled.
        """
        if not self.allow():
            return

        # Log button events to help debug whether interpreter emits clicks
        if ev.type == EventType.BUTTON and ev.button:
            print("[BTN]", ev.button.name, ev.button.action)

        if ev.type == EventType.MOVE and ev.move:
            self.mouse.move(ev.move.dx, ev.move.dy)
        elif ev.type == EventType.SCROLL and ev.scroll:
            self.mouse.scroll(ev.scroll.dx, ev.scroll.dy)
        elif ev.type == EventType.BUTTON and ev.button:
            if ev.button.name == MouseButton.LEFT:
                MIN_PRESS_MS = 55  # real-time minimum press duration

                if ev.button.action == ButtonAction.DOWN:
                    # ignore repeated DOWN spam while already down
                    if not self._left_is_down:
                        self._left_is_down = True
                        self._left_down_t = time.monotonic()
                        self.mouse.button_left(True)

                elif ev.button.action == ButtonAction.UP:
                    # enforce real time minimum press so apps reliably register clicks/drags
                    if self._left_is_down:
                        if self._left_down_t is not None:
                            elapsed_ms = (time.monotonic() - self._left_down_t) * 1000.0
                            remaining = (MIN_PRESS_MS - elapsed_ms) / 1000.0
                            if remaining > 0:
                                time.sleep(remaining)

                        self.mouse.button_left(False)
                        self._left_is_down = False
                        self._left_down_t = None
                # CLICK is optional — if you keep CLICK, you’ll map it later
            elif ev.button.name == MouseButton.RIGHT:
                if ev.button.action == ButtonAction.DOWN:
                    self.mouse.button_right(True)
                elif ev.button.action == ButtonAction.UP:
                    self.mouse.button_right(False)

    def _release_all(self) -> None:
        # Make absolutely sure nothing is stuck down.
        self.mouse.button_left(False)
        self.mouse.button_right(False)
        self._left_is_down = False
        self._left_down_t = None
