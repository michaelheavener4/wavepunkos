from __future__ import annotations

from dataclasses import dataclass
from evdev import UInput, ecodes as e


@dataclass
class UInputMouse:
    """
    Minimal mouse injector using Linux uinput.
    Keep it boring. The interpreter is the brain.
    """
    ui: UInput

    @classmethod
    def create(cls) -> "UInputMouse":
        caps = {
            e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT],
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL],
        }
        ui = UInput(caps, name="WavePunkOS Virtual Mouse")
        return cls(ui=ui)

    def move(self, dx: int, dy: int) -> None:
        if dx:
            self.ui.write(e.EV_REL, e.REL_X, int(dx))
        if dy:
            self.ui.write(e.EV_REL, e.REL_Y, int(dy))
        self.ui.syn()

    def scroll(self, dx: int, dy: int) -> None:
        if dx:
            self.ui.write(e.EV_REL, e.REL_HWHEEL, int(dx))
        if dy:
            # Keep raw wheel sign here. Do direction mapping in the interpreter
            # (via ScrollPhysics.invert_y) so we don't double-invert.
            self.ui.write(e.EV_REL, e.REL_WHEEL, int(dy))
        self.ui.syn()

    def button_left(self, down: bool) -> None:
        self.ui.write(e.EV_KEY, e.BTN_LEFT, 1 if down else 0)
        self.ui.syn()

    def button_right(self, down: bool) -> None:
        self.ui.write(e.EV_KEY, e.BTN_RIGHT, 1 if down else 0)
        self.ui.syn()

    def close(self) -> None:
        self.ui.close()
