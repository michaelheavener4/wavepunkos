from __future__ import annotations

import time
import cv2
import os
import json
from pathlib import Path

from wavepunkos.core.control import ControlState
from wavepunkos.core.ipc_state import init_enabled, get_enabled
from wavepunkos.core.config import DEFAULT_PRESET
from wavepunkos.interpreter.state_machine import Interpreter
from wavepunkos.injector.uinput_mouse import UInputMouse
from wavepunkos.runtime.kill_switch import KillSwitch
from wavepunkos.sensor.webcam_mp import WebcamMPSrc
from wavepunkos.runtime.calibration import Calibrator, save_profile, load_profile


def _default_feel_log_path() -> str:
    outdir = Path.home() / ".cache" / "wavepunkos" / "feel_logs"
    outdir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    return str(outdir / f"feel_{ts}.jsonl")


def main():
    state = ControlState(_enabled=True)
    init_enabled(True)

    interp = Interpreter(DEFAULT_PRESET)
    mouse = UInputMouse.create()
    ks = KillSwitch(state=state, interp=interp, mouse=mouse)

    # Load saved calibration profile (if present) and apply to interpreter thresholds
    prof = load_profile()
    if prof:
        try:
            interp._index.p_on = float(prof.get("fast_down", interp._index.p_on))
            interp._index.p_off = float(prof.get("fast_up", interp._index.p_off))
            interp._middle.p_on = float(prof.get("mid_down", interp._middle.p_on))
            interp._middle.p_off = float(prof.get("mid_up", interp._middle.p_off))
            print("[Calibration] loaded profile and applied thresholds")
        except Exception:
            print("[Calibration] failed to apply profile")

    cal = Calibrator()
    calibrating = False

    src = WebcamMPSrc(cam_index=0, mirror=True)

    print("[WavePunkOS] Webcam runtime (position-only). ESC to quit.")
    FEEL_LOG_PATH = os.environ.get("FEEL_LOG_PATH")  # still allow override
    AUTO_LOG = True  # dev patch: always log unless explicitly disabled

    _feel_f = None
    if AUTO_LOG:
        if not FEEL_LOG_PATH:
            FEEL_LOG_PATH = _default_feel_log_path()
        Path(FEEL_LOG_PATH).expanduser().parent.mkdir(parents=True, exist_ok=True)
        _feel_f = open(FEEL_LOG_PATH, "a", buffering=1)
        print(f"[FeelLog] writing {FEEL_LOG_PATH}")
    try:
        while True:
            # sync ON/OFF from daemon
            state.set_enabled(get_enabled())

            t_ms = int(time.time() * 1000)
            ks.guard(t_ms=t_ms)

            hf, dbg = src.read()
            events = []
            if hf is not None:
                events = interp.process(hf)
                for ev in events:
                    ks.apply(ev)

            # optional feel logging
            if _feel_f is not None:
                hand = None
                if hf is not None and len(hf.hands) > 0:
                    hand = hf.hands[0]
                rec = {
                    "t_ms": int(t_ms),
                    "pose": getattr(hand, "pose", None) if hand else None,
                    "grip": getattr(hand, "grip", None) if hand else None,
                    "conf": getattr(hand, "confidence", None) if hand else None,
                    "hand_x": (hand.pos_norm[0] if (hand and getattr(hand, 'pos_norm', None) is not None) else None),
                    "hand_y": (hand.pos_norm[1] if (hand and getattr(hand, 'pos_norm', None) is not None) else None),
                    "pinch_i": getattr(getattr(hand, "pinch", None), "index", None) if hand else None,
                    "pinch_m": getattr(getattr(hand, "pinch", None), "middle", None) if hand else None,
                    "mode": str(getattr(interp, "mode", None)),
                    "events": [str(ev) for ev in events],
                    "scroll_offset_px": getattr(interp, "_dbg_scroll_offset_px", None),
                }
                _feel_f.write(json.dumps(rec) + "\n")
                _feel_f.flush()

            # calibration wizard: draw overlay and collect samples when active
            if calibrating:
                cal.update(hand if (hf is not None and len(hf.hands) > 0) else None, t_ms)
                if dbg is not None:
                    inst = cal.instruction()
                    cv2.putText(dbg, inst, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
                if cal.done:
                    r = cal.finalize()
                    save_profile(r)
                    print("[Calibration] saved profile:", r)
                    calibrating = False

            if dbg is not None:
                cv2.imshow("WavePunkOS Playground (Webcam)", dbg)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC
                    break
                if key in (ord('c'), ord('C')):
                    calibrating = True
                    cal.start()

            time.sleep(0.005)
    finally:
        state.set_enabled(False)
        ks.guard(t_ms=int(time.time() * 1000))
        src.close()
        mouse.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
