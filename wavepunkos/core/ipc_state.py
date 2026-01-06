from __future__ import annotations

from pathlib import Path

STATE_PATH = Path("/tmp/wavepunkos_enabled")


def init_enabled(default: bool = True) -> None:
    if not STATE_PATH.exists():
        set_enabled(default)


def set_enabled(enabled: bool) -> None:
    STATE_PATH.write_text("1" if enabled else "0")


def get_enabled() -> bool:
    try:
        return STATE_PATH.read_text().strip() == "1"
    except FileNotFoundError:
        return True
