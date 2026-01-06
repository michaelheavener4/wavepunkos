from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

"""
WavePunkOS Feel Recorder
Writes JSONL logs to ~/.cache/wavepunkos/feel_logs/feel_<timestamp>.jsonl
One line = one frame's observation + emitted events.
"""


def _ser(x):
    if x is None:
        return None
    if is_dataclass(x):
        return asdict(x)
    if hasattr(x, "__dict__"):
        return dict(x.__dict__)
    return str(x)


def log_path():
    outdir = Path.home() / ".cache" / "wavepunkos" / "feel_logs"
    outdir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    return outdir / f"feel_{ts}.jsonl"


if __name__ == "__main__":
    p = log_path()
    print(f"[FeelRecorder] writing to {p}")

    # NOTE: easiest integration point is inside your runtime loop.
    # For now, just tell user to enable FEEL_LOG_PATH in config or env.
    print("[FeelRecorder] Set FEEL_LOG_PATH env var and run run_webcam.py (next step).")
    print("[FeelRecorder] Example:")
    print(f"  FEEL_LOG_PATH='{p}' PYTHONPATH=. python wavepunkos/runtime/run_webcam.py")
