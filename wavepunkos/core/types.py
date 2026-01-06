"""
WavePunkOS — CORE CONTRACTS (NON-NEGOTIABLE)

This file is the SINGLE SOURCE OF TRUTH for WavePunkOS v1.

Any AI generating code for this project MUST obey the rules and contracts defined here.

Foundation reference: docs/00_foundation.md
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, List


# ============================================================
# Tracker → Interpreter (Camera / Vision → Logic)
# ============================================================

Vec3 = Tuple[float, float, float]


@dataclass(frozen=True)
class PinchSignals:
    """Pinch strengths in range [0.0 – 1.0]."""
    index: float
    middle: float
    ring: float = 0.0


@dataclass(frozen=True)
class HandObservation:
    """
    A single hand observation for one frame.

    pos_norm MUST be a stable anatomical reference point
    (palm center or index MCP), expressed in normalized
    camera coordinates (x, y, z).
    """
    hand_id: int
    present: bool
    confidence: float
    handedness: str          # "left" | "right" | "unknown"
    pos_norm: Vec3
    pinch: PinchSignals
    landmarks_norm: Optional[List[Vec3]] = None  # ONLY populated in Playground / Debug mode


@dataclass(frozen=True)
class HandFrame:
    """A timestamped snapshot from the tracker."""
    t_ms: int
    hands: Tuple[HandObservation, ...]


# ============================================================
# Interpreter → Injector (Logic → OS Input)
# ============================================================

class Mode(str, Enum):
    IDLE = "IDLE"
    CONTACT = "CONTACT"
    DRAG = "DRAG"
    SCROLL = "SCROLL"
    DRAG_SCROLL = "DRAG_SCROLL"
    LOST = "LOST"
    OFF = "OFF"   # panic / disabled


class EventType(str, Enum):
    MOVE = "MOVE"
    BUTTON = "BUTTON"
    SCROLL = "SCROLL"
    MODE = "MODE"
    NOOP = "NOOP"


class MouseButton(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class ButtonAction(str, Enum):
    DOWN = "DOWN"
    UP = "UP"
    CLICK = "CLICK"


@dataclass(frozen=True)
class MoveEvent:
    dx: int
    dy: int


@dataclass(frozen=True)
class ButtonEvent:
    name: MouseButton
    action: ButtonAction


@dataclass(frozen=True)
class ScrollEvent:
    dx: int
    dy: int


@dataclass(frozen=True)
class ModeEvent:
    state: Mode


@dataclass(frozen=True)
class InputEvent:
    """
    A single output event from the interpreter.

    Exactly ONE payload field must be non-None depending on `type`.
    """
    t_ms: int
    type: EventType
    move: Optional[MoveEvent] = None
    button: Optional[ButtonEvent] = None
    scroll: Optional[ScrollEvent] = None
    mode: Optional[ModeEvent] = None


def clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x
