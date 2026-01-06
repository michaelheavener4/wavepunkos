from __future__ import annotations

import time
from wavepunkos.core.types import (
	HandFrame, HandObservation, PinchSignals
)
from wavepunkos.core.config import DEFAULT_PRESET
from wavepunkos.interpreter.state_machine import Interpreter
from wavepunkos.injector.uinput_mouse import UInputMouse


def fake_frame(t_ms: int, x: float, y: float, pinch: bool) -> HandFrame:
	h = HandObservation(
		hand_id=1,
		present=True,
		confidence=0.95,
		handedness="right",
		pos_norm=(x, y, 0.0),
		pinch=PinchSignals(index=1.0 if pinch else 0.0, middle=0.0),
		landmarks_norm=None,
	)
	return HandFrame(t_ms=t_ms, hands=(h,))


def main():
	interp = Interpreter(DEFAULT_PRESET)
	mouse = UInputMouse.create()

	print("WavePunkOS fake input demo. Ctrl+C to stop.")
	t = 0
	try:
		# move right while pinched
		for i in range(100):
			frame = fake_frame(t, 0.4 + i * 0.002, 0.5, pinch=True)
			for ev in interp.process(frame):
				if ev.move:
					mouse.move(ev.move.dx, ev.move.dy)
				if ev.button:
					if ev.button.name.value == "LEFT":
						mouse.button_left(ev.button.action.value == "DOWN")
			t += 16
			time.sleep(0.016)

		# release pinch (click or drag release)
		for _ in range(10):
			frame = fake_frame(t, 0.6, 0.5, pinch=False)
			for ev in interp.process(frame):
				if ev.button and ev.button.action.value == "UP":
					mouse.button_left(False)
			t += 16
			time.sleep(0.016)

	finally:
		mouse.close()
		print("done")


if __name__ == "__main__":
	main()

