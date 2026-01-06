from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple
from collections import deque

import cv2
import mediapipe as mp

from wavepunkos.core.types import HandFrame, HandObservation, PinchSignals


def _dist(a, b):
    dx = a.x - b.x
    dy = a.y - b.y
    dz = a.z - b.z
    return (dx*dx + dy*dy + dz*dz) ** 0.5


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _grip_score(lm) -> float:
    """
    0..1 mouse-grip score.
    Targets: cupped/relaxed hand like holding a mouse.
    Rejects: tight fist and fully splayed open hand.
    """

    def clamp01(x: float) -> float:
        return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x

    palm = _dist(lm[5], lm[17]) + 1e-6

    # Palm center approx: average of MCPs (index/middle/ring/pinky) + wrist
    cx = (lm[0].x + lm[5].x + lm[9].x + lm[13].x + lm[17].x) / 5.0
    cy = (lm[0].y + lm[5].y + lm[9].y + lm[13].y + lm[17].y) / 5.0
    cz = (lm[0].z + lm[5].z + lm[9].z + lm[13].z + lm[17].z) / 5.0

    class P: pass
    c = P(); c.x, c.y, c.z = cx, cy, cz

    tips = [8, 12, 16, 20]  # index, middle, ring, pinky tips

    # Dist of each tip to palm center
    d = [_dist(lm[i], c) / palm for i in tips]
    d_avg = sum(d) / len(d)

    # "Cup window": tips are moderately close to palm center (not too far = splayed, not too close = fist)
    # Good range typically around 1.1–1.7 (varies per camera); we map a soft peak.
    # Peak near 1.35; falloff on both sides.
    cup = 1.0 - min(1.0, abs(d_avg - 1.35) / 0.55)  # 0..1

    # Fist penalty: if tips are *very* close to palm center, it's clenched
    # (d_avg < ~0.95 is usually fist-like)
    fist = clamp01((0.95 - d_avg) / 0.25)  # 0..1

    # Open-hand penalty: if tips are far, it's splayed open
    # (d_avg > ~1.85 is very open)
    openp = clamp01((d_avg - 1.85) / 0.35)  # 0..1

    score = cup * (1.0 - 0.85 * fist) * (1.0 - 0.55 * openp)
    return clamp01(score)


@dataclass
class WebcamMPSrc:
    cam_index: int = 0
    mirror: bool = True

    def __post_init__(self) -> None:
        self.cap = cv2.VideoCapture(self.cam_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=1,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6,
        )
        self.mp_draw = mp.solutions.drawing_utils
        # calibration buffer for auto-printing stable pose stats
        self._calib = deque(maxlen=30)  # ~0.5–1s depending on fps
        self._last_pose = None
        # persistent pose state for hysteresis (e.g., MOUSE_GRIP)
        self._pose_state: Optional[str] = None
        self._last_print = 0
        self._grip_active = False

    def read(self) -> Tuple[Optional[HandFrame], Optional[any]]:
        ok, frame = self.cap.read()
        if not ok:
            return None, None

        if self.mirror:
            frame = cv2.flip(frame, 1)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self.hands.process(rgb)

        t_ms = int(time.time() * 1000)

        if not res.multi_hand_landmarks:
            return HandFrame(t_ms=t_ms, hands=()), frame

        lm = res.multi_hand_landmarks[0].landmark

        # Use index MCP (landmark 5) as stable pos reference
        x = float(lm[5].x)
        y = float(lm[5].y)
        z = float(lm[5].z)


        # landmarks:
        # 4 = thumb tip
        # 8 = index tip
        # 12 = middle tip

        thumb = lm[4]
        index = lm[8]
        middle = lm[12]

        # normalize pinch distance by palm size (index MCP ↔ pinky MCP)
        palm = _dist(lm[5], lm[17]) + 1e-6

        pinch_index = max(0.0, min(1.0, 1.0 - (_dist(thumb, index) / palm)))
        pinch_middle = max(0.0, min(1.0, 1.0 - (_dist(thumb, middle) / palm)))
        pinch_ring = max(0.0, min(1.0, 1.0 - (_dist(thumb, lm[16]) / (palm + 1e-6))))

        grip = _grip_score(lm)

        # Grip hysteresis: require confident entry, allow slight relaxation to keep control
        if self._grip_active:
            self._grip_active = grip >= 0.55
        else:
            self._grip_active = grip >= 0.65

        # FINAL grip gate (mouse-like cupped hand)
        # grip must be active per hysteresis AND not actively pinching
        grip_ok = self._grip_active and (pinch_index < 0.35)

        # Simple pose classification for debugging/calibration
        if pinch_middle > 0.75:
            raw_pose = "SCROLL"
        elif pinch_index > 0.75:
            raw_pose = "PINCH"
        elif pinch_ring > 0.75:
            raw_pose = "RING"
        elif grip_ok:
            raw_pose = "MOUSE GRIP"
        elif grip < 0.25:
            raw_pose = "OPEN"
        else:
            raw_pose = "RELAXED"

        # Hysteresis for MOUSE_GRIP vs RELAXED to avoid flapping
        if self._pose_state is None:
            self._pose_state = raw_pose

        if self._pose_state == "MOUSE GRIP":
            if grip <= 0.48:
                self._pose_state = "RELAXED"
        else:
            if grip >= 0.60:
                self._pose_state = "MOUSE GRIP"

        # final pose shown uses hysteretic pose for grip/relaxed, else raw
        if raw_pose in ("MOUSE GRIP", "RELAXED"):
            pose = self._pose_state
        else:
            pose = raw_pose

        # Big label + meters (no thinking required)
        try:
            cv2.rectangle(frame, (10, 10), (520, 110), (0, 0, 0), -1)
            cv2.putText(frame, f"POSE: {pose}", (20, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)

            # show grip, confidence derived from continuous grip score, and pinch readings
            # confidence scales with grip: grip=0.0 -> conf=0.30, grip=1.0 -> conf=1.0
            conf = 0.30 + 0.70 * grip
            conf = max(0.0, min(1.0, conf))
            cv2.putText(frame, f"grip={grip:.2f} conf={conf:.2f} pinch_i={pinch_index:.2f} pinch_m={pinch_middle:.2f} pinch_r={pinch_ring:.2f}", (20, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        except Exception:
            pass

        # Auto-calibration print: when pose stays stable, print typical values
        now = time.time()
        self._calib.append((pose, grip, pinch_index))

        # If pose is stable, print once every ~2s
        if pose == self._last_pose and (now - self._last_print) > 2.0:
            vals = [(g, p) for (po, g, p) in self._calib if po == pose]
            if len(vals) >= 10:
                g_avg = sum(v[0] for v in vals) / len(vals)
                p_avg = sum(v[1] for v in vals) / len(vals)
                print(f"[CAL] pose={pose:12s} grip≈{g_avg:.2f} pinch_i≈{p_avg:.2f} n={len(vals)}")
                self._last_print = now

        self._last_pose = pose

        # Hand is considered present if landmarks detected; confidence scales with grip
        # confidence = 0.30 + 0.70 * grip
        conf = 0.30 + 0.70 * grip
        conf = max(0.0, min(1.0, conf))
        obs = HandObservation(
            hand_id=1,
            present=True,
            confidence=conf,
            handedness="unknown",
            pos_norm=(x, y, z),
            pinch=PinchSignals(index=pinch_index, middle=pinch_middle, ring=pinch_ring),
            landmarks_norm=None,
        )

        # draw landmarks for playground view
        self.mp_draw.draw_landmarks(frame, res.multi_hand_landmarks[0], self.mp_hands.HAND_CONNECTIONS)

        # overlay debug text
        try:
            cv2.putText(
                frame,
                f"grip={grip:.2f} conf={conf:.2f}  pinch_i={pinch_index:.2f} pinch_m={pinch_middle:.2f} pinch_r={pinch_ring:.2f}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
        except Exception:
            pass

        return HandFrame(t_ms=t_ms, hands=(obs,)), frame

    def close(self) -> None:
        try:
            self.hands.close()
        except Exception:
            pass
        try:
            self.cap.release()
        except Exception:
            pass
