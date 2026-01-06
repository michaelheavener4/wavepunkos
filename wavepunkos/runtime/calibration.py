from __future__ import annotations

import time, json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CalibResult:
    fast_down: float
    fast_up: float
    mid_down: float
    mid_up: float
    grip_on: float
    grip_off: float
    conf_recog: float
    invert_y: bool


def _profile_path() -> Path:
    p = Path.home() / ".config" / "wavepunkos"
    p.mkdir(parents=True, exist_ok=True)
    return p / "profile.json"


def save_profile(r: CalibResult) -> None:
    _profile_path().write_text(json.dumps(r.__dict__, indent=2))


def load_profile() -> Optional[dict]:
    p = _profile_path()
    if not p.exists():
        return None
    return json.loads(p.read_text())


def percentile(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    k = int(round((q / 100.0) * (len(xs) - 1)))
    return xs[max(0, min(len(xs) - 1, k))]


class Calibrator:
    """
    TouchID-style wizard:
    - shows text instruction
    - collects samples for a fixed duration
    - computes thresholds from percentiles
    """
    def __init__(self):
        self.step = 0
        self.step_start = None
        self.samples = {
            "grip_relaxed": [],
            "grip_mouse": [],
            "pinch_i_open": [],
            "pinch_i_pinch": [],
            "pinch_m_open": [],
            "pinch_m_pinch": [],
            "conf": [],
            "scroll_offset_sign": [],
        }
        self.anchor_y = None
        self.done = False

    def start(self):
        self.step = 0
        self.step_start = int(time.time() * 1000)
        self.done = False
        self.anchor_y = None
        for k in self.samples:
            self.samples[k].clear()

    def instruction(self) -> str:
        steps = [
            "Calibration 1/5: Hold your hand relaxed (open).",
            "Calibration 2/5: Hold your 'mouse grip' (cupped like holding a mouse).",
            "Calibration 3/5: Perform several index pinches (click).",
            "Calibration 4/5: Perform several middle pinches (scroll gesture).",
            "Calibration 5/5: Scroll test: hold scroll gesture and move hand UP then DOWN.",
        ]
        return steps[self.step] if self.step < len(steps) else "Calibration complete."

    def update(self, hand, t_ms: int):
        if self.done:
            return

        if self.step_start is None:
            self.step_start = t_ms

        # advance step every X ms (simple)
        # relaxed + grip ~2.5s, pinch steps ~5s, scroll test ~5s
        STEP_MS = 2500 if self.step in (0, 1) else 5000
        if (t_ms - self.step_start) > STEP_MS:
            self.step += 1
            self.step_start = t_ms
            self.anchor_y = None
            if self.step >= 6:
                self.done = True
            return

        if hand is None:
            return

        self.samples["conf"].append(float(hand.confidence))

        grip = float(getattr(hand, "grip", 0.0))
        pi = float(getattr(getattr(hand, "pinch", None), "index", 0.0))
        pm = float(getattr(getattr(hand, "pinch", None), "middle", 0.0))

        if self.step == 0:
            # relaxed open: capture relaxed grip and open pinch baselines
            self.samples["grip_relaxed"].append(grip)
            self.samples["pinch_i_open"].append(pi)
            self.samples["pinch_m_open"].append(pm)

        elif self.step == 1:
            # mouse grip posture
            self.samples["grip_mouse"].append(grip)

        elif self.step == 2:
            # index pinch series
            self.samples["pinch_i_pinch"].append(pi)

        elif self.step == 3:
            # middle pinch series
            self.samples["pinch_m_pinch"].append(pm)

        elif self.step == 4:
            # scroll direction test: record sign of movement relative to anchor
            y = float(hand.pos_norm[1])
            if self.anchor_y is None:
                self.anchor_y = y
                return
            dy = y - self.anchor_y
            if abs(dy) > 0.01:
                # store sign: -1 = moved down, 1 = moved up (so we can infer invert)
                self.samples["scroll_offset_sign"].append(1 if dy < 0 else -1)

    def finalize(self) -> CalibResult:
        # derive thresholds using percentiles (robust to noise)
        pi_open = self.samples["pinch_i_open"]
        pi_pinch = self.samples["pinch_i_pinch"]
        fast_down = percentile(pi_pinch, 65) or 0.67
        fast_up = percentile(pi_open, 85) or 0.56
        fast_up = min(fast_up, fast_down - 0.08)

        pm_open = self.samples["pinch_m_open"]
        pm_pinch = self.samples["pinch_m_pinch"]
        mid_down = percentile(pm_pinch, 70) or 0.78
        mid_up = percentile(pm_open, 90) or 0.62
        mid_up = min(mid_up, mid_down - 0.10)

        g_rel = self.samples["grip_relaxed"]
        g_mouse = self.samples["grip_mouse"]
        grip_on = percentile(g_mouse, 40) or 0.60
        grip_off = percentile(g_rel, 90) or 0.48
        grip_off = min(grip_off, grip_on - 0.08)

        conf = self.samples["conf"]
        conf_recog = max(0.40, (percentile(conf, 20) or 0.55) - 0.05)

        sgns = self.samples["scroll_offset_sign"]
        invert_y = False
        if sgns:
            # if the majority of recorded signs indicate inverted movement, set invert
            invert_y = (sum(sgns) < 0)

        return CalibResult(
            fast_down=float(fast_down),
            fast_up=float(fast_up),
            mid_down=float(mid_down),
            mid_up=float(mid_up),
            grip_on=float(grip_on),
            grip_off=float(grip_off),
            conf_recog=float(conf_recog),
            invert_y=bool(invert_y),
        )
