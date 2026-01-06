"""
WavePunkOS — v1 Defaults (Presets)

Source of truth:
- docs/00_foundation.md
- docs/04_ai_inputs.md
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class PresetName(str, Enum):
    DEFAULT = "Default"
    PRECISION = "Precision"
    CHILL = "Chill"


@dataclass(frozen=True)
class Hysteresis:
    p_on: float = 0.80
    p_off: float = 0.60
    t_on_ms: int = 80
    t_off_ms: int = 80


@dataclass(frozen=True)
class ClickDragTuning:
    click_max_ms: int = 170
    click_move_tol_px: int = 6
    drag_hold_ms: int = 220
    double_click_ms: int = 420


@dataclass(frozen=True)
class TrackingSafety:
    min_conf: float = 0.55
    lost_timeout_ms: int = 120


@dataclass(frozen=True)
class MovementSafety:
    deadzone_px: int = 1
    max_step_frac: float = 0.20


@dataclass(frozen=True)
class OneEuroParams:
    min_cutoff_hz: float = 2.0
    beta: float = 0.06
    d_cutoff_hz: float = 1.0


@dataclass(frozen=True)
class PinchEmaParams:
    alpha: float = 0.35


@dataclass(frozen=True)
class HoverMove:
    enabled: bool = True
    min_conf: float = 0.75
    edge_margin: float = 0.06      # ignore near frame edges
    deadzone_px: int = 2           # ignore tiny jitter
    sensitivity: float = 2.6       # 2.0–3.5 typical


@dataclass(frozen=True)
class ScrollTuning:
    enabled: bool = True
    speed: float = 1.0
    invert: bool = False
    inertia: float = 0.15
    # additional tuning knobs
    gain: float = 1.4
    deadzone_px: int = 2
    max_step: int = 6


@dataclass(frozen=True)
class ScrollPhysics:
    deadzone_px: float = 22.0          # how far from anchor before it starts moving
    px_for_unit: float = 320.0         # distance that maps to ~1.0 “speed unit”
    gamma: float = 1.25                # curve steepness
    ticks_per_s_at_unit: float = 90.0  # legacy (not used by new mapping)
    max_ticks_per_s: float = 120.0     # cap (reading-friendly)
    half_life_ms: int = 320            # momentum decay (optional)
    reengage_ms: int = 420             # pump window
    invert_y: bool = False


@dataclass(frozen=True)
class AdaptationBounds:
    enabled: bool = True
    p_on_range: Tuple[float, float] = (0.70, 0.90)
    p_off_range: Tuple[float, float] = (0.50, 0.75)
    max_shift_per_min: float = 0.01
    max_hand_speed_norm: float = 0.015


@dataclass(frozen=True)
class Preset:
    name: PresetName
    pinch_index: Hysteresis
    pinch_middle: Hysteresis
    click_drag: ClickDragTuning
    tracking: TrackingSafety
    move_safety: MovementSafety
    pos_filter: OneEuroParams
    pinch_filter: PinchEmaParams
    scroll: ScrollTuning
    scroll_tuning: ScrollTuning
    scroll_physics: ScrollPhysics = ScrollPhysics()
    adaptation: AdaptationBounds = AdaptationBounds()
    hover: HoverMove = HoverMove()


DEFAULT_PRESET = Preset(
    name=PresetName.DEFAULT,
    pinch_index=Hysteresis(p_on=0.78, p_off=0.62, t_on_ms=80, t_off_ms=80),
    # Middle pinch is more occlusion-prone on webcams; use slightly easier engage
    # so scroll gesture recognition is consistent across hand angles.
    pinch_middle=Hysteresis(p_on=0.68, p_off=0.55, t_on_ms=60, t_off_ms=80),
    click_drag=ClickDragTuning(click_max_ms=170, click_move_tol_px=6, drag_hold_ms=220),
    tracking=TrackingSafety(min_conf=0.55, lost_timeout_ms=120),
    move_safety=MovementSafety(deadzone_px=1, max_step_frac=0.20),
    pos_filter=OneEuroParams(min_cutoff_hz=2.0, beta=0.06, d_cutoff_hz=1.0),
    pinch_filter=PinchEmaParams(alpha=0.35),
    scroll=ScrollTuning(enabled=True, speed=1.0, invert=False, inertia=0.15),
    scroll_tuning=ScrollTuning(gain=1.4, deadzone_px=2, max_step=6),
    scroll_physics=ScrollPhysics(deadzone_px=14.0, px_for_unit=140.0, gamma=1.35, ticks_per_s_at_unit=90.0, max_ticks_per_s=320.0, half_life_ms=320, reengage_ms=420),
    adaptation=AdaptationBounds(enabled=True),
    hover=HoverMove(enabled=True, min_conf=0.75, edge_margin=0.06, deadzone_px=4, sensitivity=2.2),
)

PRECISION_PRESET = Preset(
    name=PresetName.PRECISION,
    pinch_index=Hysteresis(p_on=0.78, p_off=0.62, t_on_ms=80, t_off_ms=80),
    pinch_middle=Hysteresis(p_on=0.68, p_off=0.55, t_on_ms=70, t_off_ms=90),
    click_drag=ClickDragTuning(click_max_ms=180, click_move_tol_px=5, drag_hold_ms=240),
    tracking=TrackingSafety(min_conf=0.58, lost_timeout_ms=110),
    move_safety=MovementSafety(deadzone_px=4, max_step_frac=0.10),
    pos_filter=OneEuroParams(min_cutoff_hz=1.5, beta=0.04, d_cutoff_hz=1.0),
    pinch_filter=PinchEmaParams(alpha=0.30),
    scroll=ScrollTuning(enabled=True, speed=0.9, invert=False, inertia=0.10),
    scroll_tuning=ScrollTuning(gain=1.4, deadzone_px=2, max_step=6),
    adaptation=AdaptationBounds(enabled=True, max_shift_per_min=0.008),
)

CHILL_PRESET = Preset(
    name=PresetName.CHILL,
    pinch_index=Hysteresis(p_on=0.78, p_off=0.62, t_on_ms=80, t_off_ms=80),
    pinch_middle=Hysteresis(p_on=0.66, p_off=0.54, t_on_ms=60, t_off_ms=90),
    click_drag=ClickDragTuning(click_max_ms=170, click_move_tol_px=7, drag_hold_ms=220),
    tracking=TrackingSafety(min_conf=0.53, lost_timeout_ms=130),
    move_safety=MovementSafety(deadzone_px=2, max_step_frac=0.14),
    pos_filter=OneEuroParams(min_cutoff_hz=2.5, beta=0.08, d_cutoff_hz=1.0),
    pinch_filter=PinchEmaParams(alpha=0.40),
    scroll=ScrollTuning(enabled=True, speed=1.1, invert=False, inertia=0.18),
    scroll_tuning=ScrollTuning(gain=1.4, deadzone_px=2, max_step=6),
    adaptation=AdaptationBounds(enabled=True, max_shift_per_min=0.012),
)

PRESETS = {
    PresetName.DEFAULT: DEFAULT_PRESET,
    PresetName.PRECISION: PRECISION_PRESET,
    PresetName.CHILL: CHILL_PRESET,
}
