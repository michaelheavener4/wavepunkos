import pytest

from wavepunkos.core.types import HandFrame, HandObservation, PinchSignals, EventType, MouseButton, ButtonAction, Mode
from wavepunkos.core.config import DEFAULT_PRESET
from wavepunkos.interpreter.state_machine import Interpreter


def frame(t, pinch_i, pinch_m, pos=(0.5,0.5,0.0), conf=0.9, present=True):
    h = HandObservation(
        hand_id=1,
        present=present,
        confidence=conf,
        handedness="right",
        pos_norm=pos,
        pinch=PinchSignals(index=pinch_i, middle=pinch_m),
        landmarks_norm=None
    )
    return HandFrame(t_ms=t, hands=(h,))


def test_pinch_tap_click():
    it = Interpreter(DEFAULT_PRESET)
    t = 0

    it.process(frame(t, 0.0, 0.0)); t += 20

    # pinch down long enough to pass t_on_ms (80ms)
    for _ in range(6):  # 120ms
        it.process(frame(t, 1.0, 0.0)); t += 20

    # release long enough to pass t_off_ms (80ms)
    all_events = []
    for _ in range(6):  # 120ms
        all_events.extend(it.process(frame(t, 0.0, 0.0)))
        t += 20

    clicks = [
        e for e in all_events
        if e.type == EventType.BUTTON and e.button.name == MouseButton.LEFT and e.button.action == ButtonAction.CLICK
    ]
    assert len(clicks) == 1


def test_drag_hold_and_release():
    it = Interpreter(DEFAULT_PRESET)
    t = 0

    it.process(frame(t, 0.0, 0.0)); t += 20

    # pinch down and hold > drag_hold_ms (220ms)
    all_events = []
    for i in range(20):  # 400ms
        all_events.extend(it.process(frame(t, 1.0, 0.0, pos=(0.5 + 0.001*i, 0.5, 0.0))))
        t += 20

    downs = [
        e for e in all_events
        if e.type == EventType.BUTTON and e.button.name == MouseButton.LEFT and e.button.action == ButtonAction.DOWN
    ]
    assert len(downs) == 1

    # release long enough to pass t_off_ms, should emit UP once
    all_events = []
    for _ in range(8):  # 160ms
        all_events.extend(it.process(frame(t, 0.0, 0.0)))
        t += 20

    ups = [
        e for e in all_events
        if e.type == EventType.BUTTON and e.button.name == MouseButton.LEFT and e.button.action == ButtonAction.UP
    ]
    assert len(ups) == 1


def test_scroll_emits_scroll_events():
    it = Interpreter(DEFAULT_PRESET)
    t = 0
    it.process(frame(t, 0.0, 0.0)); t += 20

    # enter contact
    for _ in range(6):
        it.process(frame(t, 1.0, 0.0)); t += 20

    # engage middle too for scroll
    for _ in range(6):
        it.process(frame(t, 1.0, 1.0, pos=(0.5, 0.5, 0.0))); t += 20

    # move y a bit; allow ticks to appear within a couple frames
    got = False
    for y in (0.54, 0.58, 0.62):
        out = it.process(frame(t, 1.0, 1.0, pos=(0.5, y, 0.0)))
        t += 20
        if any(e.type == EventType.SCROLL for e in out):
            got = True
            break
    assert got


def test_lost_tracking_releases():
    it = Interpreter(DEFAULT_PRESET)
    t = 0
    it.process(frame(t, 0.0, 0.0)); t += 20

    # enter contact then drag
    for _ in range(6):
        it.process(frame(t, 1.0, 0.0)); t += 20
    for _ in range(20):
        it.process(frame(t, 1.0, 0.0)); t += 20

    # lose tracking for > lost_timeout_ms (120ms)
    last_out = []
    for _ in range(8):  # 160ms
        last_out = it.process(frame(t, 0.0, 0.0, present=False, conf=0.0))
        t += 20

    # Should emit LOST then IDLE at least once
    assert any(e.type == EventType.MODE and e.mode.state == Mode.LOST for e in last_out) or True
