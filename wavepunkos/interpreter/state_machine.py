from __future__ import annotations

import math
import time
from dataclasses import dataclass

from wavepunkos.core.types import (
    HandFrame, HandObservation,
    InputEvent, EventType, Mode, ModeEvent,
    MoveEvent, ButtonEvent, ScrollEvent,
    MouseButton, ButtonAction,
)
from wavepunkos.core.config import Preset
from wavepunkos.core.one_euro import OneEuro
from wavepunkos.runtime.calibration import load_profile


@dataclass
class _DebouncedHysteresis:
    p_on: float
    p_off: float
    t_on_ms: int
    t_off_ms: int

    state: bool = False
    _candidate_since_ms: int | None = None
    _candidate_target: bool | None = None

    def update(self, value: float, t_ms: int) -> bool:
        # Decide desired target based on hysteresis thresholds
        if self.state:
            target = False if value <= self.p_off else True
        else:
            target = True if value >= self.p_on else False

        if target == self.state:
            self._candidate_since_ms = None
            self._candidate_target = None
            return self.state

        # Start or continue candidate timer
        if self._candidate_target != target:
            self._candidate_target = target
            self._candidate_since_ms = t_ms

        assert self._candidate_since_ms is not None
        elapsed = t_ms - self._candidate_since_ms
        gate = self.t_on_ms if target else self.t_off_ms
        if elapsed >= gate:
            self.state = target
            self._candidate_since_ms = None
            self._candidate_target = None
        return self.state


class Interpreter:
    """
    Deterministic WavePunkOS interpreter.
    Converts HandFrame -> list[InputEvent] according to locked plan.
    """

    def __init__(self, preset: Preset, screen_size=(1920, 1080)) -> None:
        self.preset = preset
        self.screen_w, self.screen_h = screen_size

        self.mode: Mode = Mode.IDLE
        self.off: bool = False

        # Debounced pinch thresholds — tuned for typical webcam readings.
        # Keep defaults here but allow calibration profile to override.
        # Sensible defaults (matches previous tuned values)
        self._fast_down = 0.67
        self._fast_up = 0.56
        self._mid_down = 0.78
        self._mid_up = 0.62
        self._grip_on = 0.60
        self._grip_off = 0.48
        # recognition confidence (can be lowered via calibration)
        self._conf_recog = float(self.preset.tracking.min_conf)

        # instantiate debouncers with legacy defaults; they may be adjusted below
        self._index = _DebouncedHysteresis(p_on=0.62, p_off=0.52, t_on_ms=60, t_off_ms=60)
        self._middle = _DebouncedHysteresis(p_on=0.78, p_off=0.62, t_on_ms=70, t_off_ms=70)
        self._ring = _DebouncedHysteresis(p_on=0.78, p_off=0.62, t_on_ms=70, t_off_ms=70)

        # Try to load a saved calibration profile and apply thresholds
        try:
            prof = load_profile()
            if prof:
                # apply pinch thresholds
                self._index.p_on = float(prof.get("fast_down", self._index.p_on))
                self._index.p_off = float(prof.get("fast_up", self._index.p_off))
                self._middle.p_on = float(prof.get("mid_down", self._middle.p_on))
                self._middle.p_off = float(prof.get("mid_up", self._middle.p_off))
                # store handy copies for fast-latch logic
                self._fast_down = float(prof.get("fast_down", self._fast_down))
                self._fast_up = float(prof.get("fast_up", self._fast_up))
                self._mid_down = float(prof.get("mid_down", self._mid_down))
                self._mid_up = float(prof.get("mid_up", self._mid_up))
                # confidence and grip
                self._conf_recog = float(prof.get("conf_recog", self._conf_recog))
                self._grip_on = float(prof.get("grip_on", self._grip_on))
                self._grip_off = float(prof.get("grip_off", self._grip_off))
                # apply scroll invert if present in profile
                if prof.get("invert_y") is not None and hasattr(self.preset.scroll_physics, "invert_y"):
                    self.preset.scroll_physics.invert_y = bool(prof.get("invert_y", False))
        except Exception:
            # silently ignore profile load/apply errors
            pass

        self._last_frame_t: int | None = None
        self._last_good_t: int | None = None
        self._prev_pos = None  # (x,y,z)

        # anchors
        self._anchor_hand = None
        self._anchor_cursor = (0.0, 0.0)
        self._cursor = [0.0, 0.0]  # internal accumulator

        # contact stats for click gating
        self._contact_start_ms: int | None = None
        self._contact_move_px: float = 0.0
        # click / double-click tracking
        self._last_click_ms: int | None = None
        self._click_pending: bool = False
        self._contact_down_ms: int | None = None
        # last left-button-up timestamp for double-click detection
        self._last_left_click_up_ms: int | None = None
        # index/middle chord timing (for right-click chord)
        self._idx_down_ms: int | None = None
        self._mid_down_ms: int | None = None
        self._rc_block_until: int = 0

        # drag flag
        self._left_down: bool = False

        # scroll
        self._scroll_anchor = None
        self._scroll_v = 0.0
        self._scroll_remainder = 0.0
        self._scroll_anchor_y = None
        # scroll previous normalized pos and OneEuro delta filters
        self._scroll_prev = None
        self._scroll_fdx = OneEuro(min_cutoff=2.6, beta=0.08, d_cutoff=1.2)
        self._scroll_fdy = OneEuro(min_cutoff=2.6, beta=0.08, d_cutoff=1.2)
        # scroll physics / momentum
        self._scroll_vel = 0.0
        self._scroll_last_t: int | None = None
        self._scroll_release_t: int | None = None
        # sticky scroll hold until timestamp (ms)
        self._scroll_hold_until: int = 0

        # adaptation stats (very slow, bounded)
        self._last_adapt_ms: int | None = None
        # sensitivity multiplier for cursor movement
        self.sensitivity = 2.5  # start here (2.0–3.5 is typical)
        # hover previous position (x,y) for hover-mode movement
        self._hover_prev = None  # (x,y)
        # One Euro filters for hover smoothing (filter deltas, not absolute)
        self._hover_fdx = OneEuro(min_cutoff=2.2, beta=0.06, d_cutoff=1.0)
        self._hover_fdy = OneEuro(min_cutoff=2.2, beta=0.06, d_cutoff=1.0)
        # hover cooldown to block immediate re-grab after scroll
        self._hover_block_until = 0  # ms
        # latched pinch state (stable held state)
        self._pinch_latched = False
        # fast immediate click latch (no dwell)
        self._fast_left_latched = False
        # consecutive-ms accumulator for fast index peak (ms) (legacy)
        self._pi_over_ms = 0.0
        # peak-tracking for angle-robust click arming
        self._pi_peak = 0.0
        self._pi_peak_t: int | None = None
        # latch start timestamp for minimum hold enforcement
        self._fast_latch_start_ms: int | None = None
        # last exit reason for diagnostics
        self._last_exit_reason: str | None = None

        # OneEuro filters for absolute normalized position (apply before mapping)
        pf = self.preset.pos_filter
        self._pos_fdx = OneEuro(min_cutoff=pf.min_cutoff_hz, beta=pf.beta, d_cutoff=pf.d_cutoff_hz)
        self._pos_fdy = OneEuro(min_cutoff=pf.min_cutoff_hz, beta=pf.beta, d_cutoff=pf.d_cutoff_hz)

        # click settle window (freeze pointer briefly after press)
        self._click_settle_until: int = 0
        # debug helpers
        self._dbg_scroll_offset_px: float | None = None

    def _scroll_anchor_reset(self):
        self._scroll_anchor_y = None
        self._scroll_remainder = 0.0
        self._scroll_last_t = None

    def set_off(self, off: bool, t_ms: int) -> list[InputEvent]:
        self.off = off
        if off:
            return self._enter_off(t_ms)
        # re-enable to idle
        if self.mode == Mode.OFF:
            self.mode = Mode.IDLE
            return [InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.IDLE))]
        return []

    def process(self, frame: HandFrame) -> list[InputEvent]:
        t_ms = frame.t_ms
        events: list[InputEvent] = []

        if self.off:
            if self.mode != Mode.OFF:
                events.extend(self._enter_off(t_ms))
            return events

        hand = self._select_hand(frame)

        # pre-update debounced pinch states so middle_down can keep tracking alive
        if hand is not None:
            index_down = self._index.update(hand.pinch.index, t_ms)
            middle_down = self._middle.update(hand.pinch.middle, t_ms)
            ring_down = self._ring.update(hand.pinch.ring, t_ms)
        else:
            index_down = False
            middle_down = False
            ring_down = False

        # NOTE: pinching will be computed below using a fast latch (instant DOWN, hysteretic UP)

        # record index/middle down timestamps for chord detection
        if index_down:
            if self._idx_down_ms is None:
                self._idx_down_ms = t_ms
        else:
            self._idx_down_ms = None

        if middle_down:
            if self._mid_down_ms is None:
                self._mid_down_ms = t_ms
        else:
            self._mid_down_ms = None

        # consider valid if hand is valid OR middle pinch is active (keep scroll alive)
        valid = self._is_valid(hand) or middle_down

        if valid:
            self._last_good_t = t_ms
        else:
            # reset hover when tracking lost/unreliable
            self._hover_prev = None
            self._hover_fdx.reset()
            self._hover_fdy.reset()
            # check lost timeout
            if self._last_good_t is not None and (t_ms - self._last_good_t) >= self.preset.tracking.lost_timeout_ms:
                events.extend(self._enter_lost(t_ms))
            self._last_frame_t = t_ms
            return events

        assert hand is not None

        # Fast immediate click thresholds (no dwell)
        pi = hand.pinch.index
        # Peak-based click arming (angle-robust)
        PEAK_WINDOW_MS = 70

        fast_down = pi >= self._fast_down
        fast_up = pi <= self._fast_up

        # Track a short running peak so clicks are robust to single-frame angle noise
        if self._pi_peak_t is None or (t_ms - self._pi_peak_t) > PEAK_WINDOW_MS:
            self._pi_peak = 0.0
            self._pi_peak_t = t_ms

        self._pi_peak = max(self._pi_peak, pi)

        # Arm click only when not scrolling and not using the middle (scroll) finger
        if (not self._fast_left_latched) and (not middle_down) and (self.mode != Mode.SCROLL):
            if self._pi_peak >= FAST_DOWN:
                self._fast_left_latched = True
                self._fast_latch_start_ms = t_ms
                # reset peak tracker
                self._pi_peak = 0.0
                self._pi_peak_t = None
                events.extend(self._enter_contact(hand, t_ms))
                self._rc_block_until = t_ms + 120
                return events

        # If latched, treat as still pinching until fast_up trips AND minimum hold elapsed
        pinching = False
        if self._fast_left_latched:
            can_unlatch = True
            if self._fast_latch_start_ms is not None:
                can_unlatch = (t_ms - self._fast_latch_start_ms) >= 80  # MIN_HOLD_MS = 80
            if fast_up and can_unlatch:
                # allow unlatch
                self._fast_left_latched = False
                self._fast_latch_start_ms = None
                self._last_exit_reason = "release"
                pinching = False
            else:
                pinching = True

        # compute calm / speed
        calm = self._is_calm(hand, t_ms)

        # Hover moves while not in a pinch-driven state (IDLE)
        # IDLE behavior / transitions (order matters!)
        if self.mode == Mode.IDLE:
            # block briefly after a right-click chord
            if t_ms < self._rc_block_until:
                self._hover_prev = None
                return events

            # Right-click chord: index + middle pressed near-simultaneously
            chord_window_ms = 140
            if index_down and middle_down and calm:
                if self._idx_down_ms is not None and self._mid_down_ms is not None and abs(self._idx_down_ms - self._mid_down_ms) <= chord_window_ms:
                    events.append(InputEvent(
                        t_ms=t_ms, type=EventType.BUTTON,
                        button=ButtonEvent(name=MouseButton.RIGHT, action=ButtonAction.CLICK)
                    ))
                    self._hover_prev = None
                    self._rc_block_until = t_ms + 180
                    return events

            # enter scroll: middle pinch held alone (no index latch), stable for arm_ms
            if middle_down and (not self._fast_left_latched) and self.preset.scroll.enabled:
                if self._mid_down_ms is None:
                    self._mid_down_ms = t_ms
                arm_ms = 140
                if (t_ms - self._mid_down_ms) >= arm_ms:
                    # don't enter scroll during the click settle window
                    if t_ms < self._click_settle_until:
                        pass
                    else:
                        events.extend(self._enter_scroll(hand, t_ms))
                        return events
            else:
                self._mid_down_ms = None
            # contact (index) has priority over hover
            if pinching:
                events.extend(self._enter_contact(hand, t_ms))
                return events
            elif ring_down and calm:
                # ring tap => right-click (single tap)
                events.append(InputEvent(t_ms=t_ms, type=EventType.BUTTON,
                                         button=ButtonEvent(name=MouseButton.RIGHT, action=ButtonAction.DOWN)))
                events.append(InputEvent(t_ms=t_ms, type=EventType.BUTTON,
                                         button=ButtonEvent(name=MouseButton.RIGHT, action=ButtonAction.UP)))
                # prevent hover re-grab and small jump
                self._hover_prev = None
                self._hover_block_until = t_ms + 120
                return events
            else:
                # only hover when not scrolling and not clicking
                if t_ms >= self._hover_block_until:
                    events.extend(self._maybe_emit_hover_move(hand))
                else:
                    # prevent a jump when coming out of scroll
                    self._hover_prev = None

        # bounded adaptation (only in IDLE, calm, high confidence)
        if self.mode == Mode.IDLE and calm and hand.confidence >= max(self._conf_recog, 0.60):
            self._maybe_adapt(hand, t_ms)

        elif self.mode == Mode.CONTACT:
            # While pinching: stay in contact/drag, emit moves
            if pinching:
                # freeze pointer briefly after press so targets don't slip
                if t_ms >= self._click_settle_until:
                    events.extend(self._emit_move(hand, t_ms))

                # drag entry
                if self._contact_start_ms is not None and (t_ms - self._contact_start_ms) >= self.preset.click_drag.drag_hold_ms:
                    events.extend(self._enter_drag(t_ms))
            else:
                # pinch released -> mouse up
                events.extend(self._exit_contact(hand, t_ms, calm))

        elif self.mode == Mode.DRAG:
            # keep dragging while pinching; release when pinch ends
            if pinching:
                events.extend(self._emit_move(hand, t_ms))
            else:
                events.extend(self._exit_drag(t_ms))

        elif self.mode == Mode.SCROLL:
            # sticky: tolerate brief middle dropout
            if middle_down:
                # refresh hold window
                self._scroll_hold_until = t_ms + 150

            if t_ms <= self._scroll_hold_until:
                # while within hold window, emit scroll only (no cursor moves)
                events.extend(self._maybe_emit_scroll(hand, t_ms))
            else:
                # exit scroll cleanly
                self._scroll_anchor_y = None
                self._scroll_remainder = 0.0
                self._scroll_vel = 0.0
                self._hover_prev = None
                self._hover_block_until = t_ms + 160
                self.mode = Mode.IDLE
                events.append(InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.IDLE)))

        elif self.mode == Mode.DRAG_SCROLL:
            # Scroll while keeping LEFT held down (for text selection)
            if middle_down:
                events.extend(self._maybe_emit_scroll(hand, t_ms))
            else:
                # return to drag (still holding left)
                self._scroll_anchor_y = None
                self._hover_prev = None
                self.mode = Mode.DRAG
                events.append(InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.DRAG)))

        elif self.mode in (Mode.LOST, Mode.OFF):
            # Shouldn't happen here, but recover to IDLE
            self.mode = Mode.IDLE
            events.append(InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.IDLE)))

        self._last_frame_t = t_ms
        return events

    # ---------------------- selection / validity ----------------------

    def _select_hand(self, frame: HandFrame) -> HandObservation | None:
        # v1: choose highest-confidence present hand
        best = None
        for h in frame.hands:
            if not h.present:
                continue
            if best is None or h.confidence > best.confidence:
                best = h
        return best

    def _is_valid(self, hand: HandObservation | None) -> bool:
        return bool(hand and hand.present and hand.confidence >= self.preset.tracking.min_conf)

    def _is_calm(self, hand: HandObservation, t_ms: int) -> bool:
        if self._prev_pos is None or self._last_frame_t is None:
            self._prev_pos = hand.pos_norm
            return True
        px, py, pz = self._prev_pos
        x, y, z = hand.pos_norm
        dx, dy = x - px, y - py
        dist = math.hypot(dx, dy)
        self._prev_pos = hand.pos_norm
        return dist <= self.preset.adaptation.max_hand_speed_norm

    # ---------------------- state transitions ----------------------

    def _enter_contact(self, hand: HandObservation, t_ms: int) -> list[InputEvent]:
        self.mode = Mode.CONTACT
        self._anchor_hand = hand.pos_norm
        self._anchor_cursor = (self._cursor[0], self._cursor[1])
        # immediate left-button down to emulate a real mouse press
        self._contact_start_ms = t_ms
        self._contact_down_ms = t_ms
        # settle window to keep pointer stable for short taps
        self._click_settle_until = t_ms + 60
        self._contact_move_px = 0.0
        self._left_down = True
        # latch pinch-held state
        self._pinch_latched = True
        out = [
            InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.CONTACT)),
            InputEvent(t_ms=t_ms, type=EventType.BUTTON, button=ButtonEvent(name=MouseButton.LEFT, action=ButtonAction.DOWN)),
        ]
        return out

    def _exit_contact(self, hand: HandObservation, t_ms: int, calm: bool) -> list[InputEvent]:
        # Determine click: duration + movement + armed
        out: list[InputEvent] = []
        # Decide if this was a tap (short contact) -> emit left click (down/up)
        held = (t_ms - self._contact_down_ms) if self._contact_down_ms is not None else 999999
        armed = calm and hand.confidence >= self._conf_recog

        if self._left_down:
            # release left button on contact exit, but enforce minimum press duration
            MIN_PRESS_MS = 55
            t_up = t_ms
            if self._contact_down_ms is not None:
                t_up = max(t_ms, self._contact_down_ms + MIN_PRESS_MS)

            out.append(InputEvent(t_ms=t_up, type=EventType.BUTTON,
                                 button=ButtonEvent(name=MouseButton.LEFT, action=ButtonAction.UP)))
            self._left_down = False
            # record this up for potential double-click (no auto extra click emitted)
            self._last_left_click_up_ms = t_up

        # clear latched pinch
        self._pinch_latched = False

        # clear contact down marker
        self._contact_down_ms = None

        # clear fast latch when contact ends
        self._fast_left_latched = False
        self._pi_over_ms = 0.0
        self._pi_peak = 0.0
        self._pi_peak_t = None

        self.mode = Mode.IDLE
        self._clear_contact()
        out.append(InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.IDLE)))
        return out

    def _enter_drag(self, t_ms: int) -> list[InputEvent]:
        if self.mode != Mode.CONTACT or self._left_down:
            return []
        self.mode = Mode.DRAG
        self._left_down = True
        return [
            InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.DRAG)),
            InputEvent(t_ms=t_ms, type=EventType.BUTTON, button=ButtonEvent(name=MouseButton.LEFT, action=ButtonAction.DOWN)),
        ]

    def _exit_drag(self, t_ms: int) -> list[InputEvent]:
        out: list[InputEvent] = []
        if self._left_down:
            # enforce minimum press duration for drag release as well
            MIN_PRESS_MS = 55
            t_up = t_ms
            if self._contact_down_ms is not None:
                t_up = max(t_ms, self._contact_down_ms + MIN_PRESS_MS)
            out.append(InputEvent(t_ms=t_up, type=EventType.BUTTON,
                                 button=ButtonEvent(name=MouseButton.LEFT, action=ButtonAction.UP)))
        self._left_down = False
        # clear latched pinch and fast latch
        self._pinch_latched = False
        self._fast_left_latched = False
        self._pi_over_ms = 0.0
        self.mode = Mode.IDLE
        self._clear_contact()
        out.append(InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.IDLE)))
        return out

    def _enter_scroll(self, hand: HandObservation, t_ms: int) -> list[InputEvent]:
        self.mode = Mode.SCROLL
        # switch to anchor-based scroll: store vertical anchor and reset integrators
        self._hover_prev = None
        self._scroll_anchor_y = hand.pos_norm[1]
        self._scroll_remainder = 0.0
        self._scroll_vel = 0.0
        self._scroll_last_t = t_ms
        # short grace to avoid hover bleed when entering
        self._hover_block_until = t_ms + 140
        return [InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.SCROLL))]

    def _enter_lost(self, t_ms: int) -> list[InputEvent]:
        out: list[InputEvent] = []
        # safety releases
        if self._left_down:
            out.append(InputEvent(t_ms=t_ms, type=EventType.BUTTON,
                                 button=ButtonEvent(name=MouseButton.LEFT, action=ButtonAction.UP)))
        self._left_down = False
        # clear fast latch/counters when lost
        self._fast_left_latched = False
        self._pi_over_ms = 0.0
        self._pi_peak = 0.0
        self._pi_peak_t = None
        self.mode = Mode.LOST
        self._clear_contact()
        self._scroll_anchor = None
        out.append(InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.LOST)))
        # immediately fall back to IDLE after emitting LOST
        self.mode = Mode.IDLE
        out.append(InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.IDLE)))
        # reset hover when lost
        self._hover_prev = None
        self._hover_fdx.reset()
        self._hover_fdy.reset()
        # reset scroll helpers
        self._scroll_prev = None
        self._scroll_fdx.reset()
        self._scroll_fdy.reset()
        return out

    def _enter_off(self, t_ms: int) -> list[InputEvent]:
        out: list[InputEvent] = []
        if self._left_down:
            out.append(InputEvent(t_ms=t_ms, type=EventType.BUTTON,
                                 button=ButtonEvent(name=MouseButton.LEFT, action=ButtonAction.UP)))
        self._left_down = False
        # clear fast latch/counters when turned off
        self._fast_left_latched = False
        self._pi_over_ms = 0.0
        self.mode = Mode.OFF
        self._clear_contact()
        self._scroll_anchor = None
        out.append(InputEvent(t_ms=t_ms, type=EventType.MODE, mode=ModeEvent(state=Mode.OFF)))
        # reset hover when turned off
        self._hover_prev = None
        self._hover_fdx.reset()
        self._hover_fdy.reset()
        # reset scroll helpers
        self._scroll_prev = None
        self._scroll_fdx.reset()
        self._scroll_fdy.reset()
        return out

    # ---------------------- emitters ----------------------

    def _emit_move(self, hand: HandObservation, t_ms: int) -> list[InputEvent]:
        if self._anchor_hand is None:
            return []
        ax, ay, az = self._anchor_hand
        # apply OneEuro filtering to absolute normalized position before mapping
        now = t_ms / 1000.0
        x_raw, y_raw, z = hand.pos_norm
        x = self._pos_fdx.apply(x_raw, now)
        y = self._pos_fdy.apply(y_raw, now)
        # map normalized delta to pixels and apply sensitivity
        dx_px = (x - ax) * self.screen_w * self.sensitivity
        dy_px = (y - ay) * self.screen_h * self.sensitivity

        # convert to absolute target cursor (anchored)
        target_x = self._anchor_cursor[0] + dx_px
        target_y = self._anchor_cursor[1] + dy_px

        # step toward target from current internal cursor
        step_x = int(round(target_x - self._cursor[0]))
        step_y = int(round(target_y - self._cursor[1]))

        # deadzone
        dz_px = max(self.preset.move_safety.deadzone_px, 2)
        if abs(step_x) <= dz_px and abs(step_y) <= dz_px:
            return []

        # cap step
        cap_x = int(self.preset.move_safety.max_step_frac * self.screen_w)
        cap_y = int(self.preset.move_safety.max_step_frac * self.screen_h)
        step_x = max(-cap_x, min(cap_x, step_x))
        step_y = max(-cap_y, min(cap_y, step_y))

        self._cursor[0] += step_x
        self._cursor[1] += step_y
        self._contact_move_px += math.hypot(step_x, step_y)

        return [InputEvent(t_ms=t_ms, type=EventType.MOVE, move=MoveEvent(dx=step_x, dy=step_y))]

    def _emit_scroll(self, hand: HandObservation, t_ms: int) -> list[InputEvent]:
        # legacy scroll emitter retained for compatibility; prefer _maybe_emit_scroll
        if self._scroll_anchor is None:
            self._scroll_anchor = hand.pos_norm
            return []
        sx, sy, sz = self._scroll_anchor
        x, y, z = hand.pos_norm
        dy_norm = (y - sy)
        if self.preset.scroll.invert:
            dy_norm *= -1.0

        # map normalized delta to ticks
        base_scale = 240.0 * self.preset.scroll.speed
        desired = -dy_norm * base_scale

        # inertia (simple velocity smoothing)
        inertia = self.preset.scroll.inertia
        if inertia > 0.0:
            self._scroll_v = (1.0 - inertia) * self._scroll_v + inertia * desired
            val = self._scroll_v
        else:
            val = desired

        # integrate and emit integer ticks
        total = self._scroll_remainder + val
        ticks = int(total)
        self._scroll_remainder = total - ticks

        if ticks == 0:
            return []
        return [InputEvent(t_ms=t_ms, type=EventType.SCROLL, scroll=ScrollEvent(dx=0, dy=ticks))]

    def _clear_contact(self) -> None:
        self._anchor_hand = None
        self._contact_start_ms = None
        self._contact_move_px = 0.0

    def _ev_scroll(self, dx: int, dy: int) -> InputEvent:
        t_ms = int(time.time() * 1000)
        return InputEvent(t_ms=t_ms, type=EventType.SCROLL, scroll=ScrollEvent(dx=dx, dy=dy))

    # ---------------------- adaptation ----------------------

    def _maybe_adapt(self, hand: HandObservation, t_ms: int) -> None:
        if not self.preset.adaptation.enabled:
            return
        if self._last_adapt_ms is None:
            self._last_adapt_ms = t_ms
            return
        dt = t_ms - self._last_adapt_ms
        if dt < 5000:  # adapt at most every 5s
            return

        # bounded, tiny drift based on current pinch strength.
        # Goal: if user consistently has higher/lower pinch strength at "rest",
        # slightly shift OFF threshold toward observed rest.
        shift_per_min = self.preset.adaptation.max_shift_per_min
        shift = shift_per_min * (dt / 60000.0)

        # If rest pinch strength is high, raise thresholds slightly; else lower slightly.
        rest = hand.pinch.index
        center = (self._index.p_on + self._index.p_off) / 2.0
        direction = 1.0 if rest > center else -1.0

        new_p_on = self._index.p_on + direction * shift
        new_p_off = self._index.p_off + direction * shift

        lo_on, hi_on = self.preset.adaptation.p_on_range
        lo_off, hi_off = self.preset.adaptation.p_off_range
        self._index.p_on = max(lo_on, min(hi_on, new_p_on))
        self._index.p_off = max(lo_off, min(hi_off, new_p_off))

        self._last_adapt_ms = t_ms

    def _scroll_reset(self):
        self._scroll_prev = None
        self._scroll_remainder = 0.0
        self._scroll_vel = 0.0
        self._scroll_last_t = None
        self._scroll_release_t = None
        self._scroll_fdx.reset()
        self._scroll_fdy.reset()

    def _scroll_momentum_step(self, dt: float, t_ms: int):
        """
        Continue scrolling after release with exponential decay.
        """
        sp = self.preset.scroll_physics
        if abs(self._scroll_vel) < 0.5:
            self._scroll_vel = 0.0
            return []

        # decay using half-life
        half = max(1e-3, sp.half_life_ms / 1000.0)
        decay = 0.5 ** (dt / half)
        self._scroll_vel *= decay

        ticks_f = self._scroll_vel * dt
        self._scroll_remainder += ticks_f
        ticks = int(self._scroll_remainder)
        self._scroll_remainder -= ticks

        if ticks == 0:
            return []
        return [self._ev_scroll(0, ticks)]

    def _maybe_emit_scroll(self, hand: HandObservation, t_ms: int):
        # Displacement-based scroll mapping (pixel-precise, immediate direction changes)
        sp = self.preset.scroll_physics
        events: list[InputEvent] = []

        # init
        if self._scroll_last_t is None:
            self._scroll_last_t = t_ms
            # set anchor on first valid call
            if self._scroll_anchor_y is None and hand is not None:
                self._scroll_anchor_y = hand.pos_norm[1]
            return events

        self._scroll_last_t = t_ms

        # Scroll should be robust to brief confidence dips. Use a slightly lower
        # actuation threshold than general recognition confidence so the gesture
        # doesn't "randomly" stop while the pinch is still clearly held.
        CONF_ACT = max(0.40, self._conf_recog - 0.10)
        if hand is None or hand.confidence < CONF_ACT:
            return events

        y = hand.pos_norm[1]

        # set anchor once on entry
        if self._scroll_anchor_y is None:
            self._scroll_anchor_y = y
            return events

        # parameters (tuned from feel logs)
        PX_PER_TICK = 26.0
        MAX_TICKS_PER_FRAME = 6
        deadzone = max(sp.deadzone_px, 10.0)

        # compute displacement in pixels (positive = hand moved down)
        offset_px = (y - self._scroll_anchor_y) * self.screen_h

        # clutch: slide anchor toward hand if you pull too far (allows long drags)
        CLUTCH_PX = 260.0
        if abs(offset_px) > CLUTCH_PX:
            excess = abs(offset_px) - CLUTCH_PX
            shift = (excess / float(self.screen_h)) * (1 if offset_px > 0 else -1)
            self._scroll_anchor_y += shift
            # recompute offset after shifting anchor
            offset_px = (y - self._scroll_anchor_y) * self.screen_h

        # store debug offset for logging
        self._dbg_scroll_offset_px = float(offset_px)

        # apply explicit invert toggle from scroll_physics
        sign = 1.0 if offset_px < 0 else -1.0
        if getattr(sp, "invert_y", False):
            sign = -sign

        if abs(offset_px) <= deadzone:
            return events

        # convert to signed tick delta based on displacement beyond deadzone
        delta_ticks = sign * ((abs(offset_px) - deadzone) / max(1e-6, PX_PER_TICK))

        # accumulate fractional ticks
        self._scroll_remainder += delta_ticks

        ticks = int(self._scroll_remainder)
        if ticks != 0:
            # clamp per frame
            if ticks > MAX_TICKS_PER_FRAME:
                ticks = MAX_TICKS_PER_FRAME
            elif ticks < -MAX_TICKS_PER_FRAME:
                ticks = -MAX_TICKS_PER_FRAME

            self._scroll_remainder -= ticks
            events.append(self._ev_scroll(0, ticks))

        return events

    # ---------------------- hover helpers ----------------------

    def _hover_ok(self, h: HandObservation) -> bool:
        hv = self.preset.hover
        if not hv.enabled:
            return False
        if not h.present or h.confidence < hv.min_conf:
            return False
        x, y, _ = h.pos_norm
        m = hv.edge_margin
        if x < m or x > (1.0 - m) or y < m or y > (1.0 - m):
            return False
        return True

    def _maybe_emit_hover_move(self, h: HandObservation):
        hv = self.preset.hover

        if not self._hover_ok(h):
            # reset hover state and filters
            self._hover_prev = None
            self._hover_fdx.reset()
            self._hover_fdy.reset()
            return []

        # raw normalized position (do NOT filter absolute position)
        x, y, _ = h.pos_norm

        if self._hover_prev is None:
            self._hover_prev = (x, y)
            return []

        px, py = self._hover_prev
        # compute raw pixel deltas from raw normalized positions
        dx = (x - px) * self.screen_w * hv.sensitivity
        dy = (y - py) * self.screen_h * hv.sensitivity

        # filter the deltas (avoid rubber-banding by smoothing movement, not target)
        now = time.time()
        dx = self._hover_fdx.apply(dx, now)
        dy = self._hover_fdy.apply(dy, now)

        # update previous with raw values (so we keep integrating raw input)
        self._hover_prev = (x, y)

        # deadzone (coarse)
        if abs(dx) < hv.deadzone_px:
            dx = 0
        if abs(dy) < hv.deadzone_px:
            dy = 0

        # tiny hardware deadzone to remove 1-2px jitter without adding lag
        if abs(dx) < 2:
            dx = 0
        if abs(dy) < 2:
            dy = 0

        # micro adaptive deadzone to remove tiny jitter
        speed = abs(dx) + abs(dy)
        dz = 2 if speed > 8 else 4
        if abs(dx) < dz:
            dx = 0
        if abs(dy) < dz:
            dy = 0

        if dx == 0 and dy == 0:
            return []

        # reuse your existing cap (max_step_frac) for safety
        max_dx = int(self.preset.move_safety.max_step_frac * self.screen_w)
        max_dy = int(self.preset.move_safety.max_step_frac * self.screen_h)

        dx = int(max(-max_dx, min(max_dx, dx)))
        dy = int(max(-max_dy, min(max_dy, dy)))

        # pixel snapping at rest: if movement is <=1px, treat as settled
        if abs(dx) <= 1 and abs(dy) <= 1:
            return []

        t_ms = int(time.time() * 1000)
        return [InputEvent(t_ms=t_ms, type=EventType.MOVE, move=MoveEvent(dx=dx, dy=dy))]
