from __future__ import annotations

import time
from dataclasses import dataclass

from wavepunkos.core.control import ControlState
from wavepunkos.core.config import DEFAULT_PRESET
from wavepunkos.core.types import HandFrame, HandObservation, PinchSignals
from wavepunkos.interpreter.state_machine import Interpreter
from wavepunkos.injector.uinput_mouse import UInputMouse
from wavepunkos.runtime.kill_switch import KillSwitch
from wavepunkos.core.ipc_state import init_enabled, get_enabled


@dataclass
class FakeSource:
    """
    Deterministic fake hand source to validate runtime wiring.
    """
    start_ms: int

    def frame(self, t_ms: int) -> HandFrame:
        dt = (t_ms - self.start_ms) / 1000.0

        # Pinch ON for 2 seconds, OFF for 2 seconds
        pinch_on = int(dt) % 4 in (0, 1)

        # When pinched: ramp across screen quickly enough to exceed deadzone
        if pinch_on:
            phase = (dt % 2.0) / 2.0  # 0..1 over 2 seconds
            x = 0.2 + 0.6 * phase     # 0.2 -> 0.8
            y = 0.5
        else:
            x, y = 0.5, 0.5

        h = HandObservation(
            hand_id=1,
            present=True,
            confidence=0.95,
            handedness="right",
            pos_norm=(x, y, 0.0),
            pinch=PinchSignals(index=1.0 if pinch_on else 0.0, middle=0.0),
            landmarks_norm=None,
        )
        return HandFrame(t_ms=t_ms, hands=(h,))


def run():
    state = ControlState(_enabled=True)
    # initialize and sync with file-based IPC
    init_enabled(True)
    state.set_enabled(get_enabled())

    interp = Interpreter(DEFAULT_PRESET)
    mouse = UInputMouse.create()
    ks = KillSwitch(state=state, interp=interp, mouse=mouse)

    src = FakeSource(start_ms=int(time.time() * 1000))

    print("[WavePunkOS] Runtime loop (FAKE SOURCE). Ctrl+C to exit.")
    print("Tip: run your control_daemon in another terminal to toggle ON/OFF.")
    print("  - Ctrl+Alt+Space toggles")
    print("  - Ctrl+Alt+Esc PANIC OFF")

    try:
        while True:
            t_ms = int(time.time() * 1000)

            # sync control state from IPC (daemon may have toggled it)
            state.set_enabled(get_enabled())

            # check control transitions (OFF releases buttons etc.)
            ks.guard(t_ms=t_ms)

            frame = src.frame(t_ms)
            events = interp.process(frame)

            for ev in events:
                ks.apply(ev)

            time.sleep(0.016)  # ~60Hz loop
    except KeyboardInterrupt:
        print("\n[WavePunkOS] exiting")
    finally:
        # Always drop buttons on exit
        state.set_enabled(False)
        ks.guard(t_ms=int(time.time() * 1000))
        mouse.close()


if __name__ == "__main__":
    run()
