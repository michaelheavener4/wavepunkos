from __future__ import annotations

import threading
import time

from wavepunkos.core.control import ControlState
from wavepunkos.ui.hotkeys import run_hotkeys
from wavepunkos.core.ipc_state import init_enabled, set_enabled
try:
    from wavepunkos.ui.tray import run_tray
except Exception:
    run_tray = None


def main():
    state = ControlState(_enabled=True)
    stop = threading.Event()

    # initialize file-based IPC state and set ON
    init_enabled(True)
    set_enabled(True)

    # Hotkeys always-on (never dependent on tray)
    t_hotkeys = threading.Thread(target=run_hotkeys, args=(state,), daemon=True)
    t_hotkeys.start()

    print("[WavePunkOS] Control daemon started.")
    print("  Hotkeys:")
    print("   - Ctrl+Alt+Space = Toggle ON/OFF")
    print("   - Ctrl+Alt+Esc   = PANIC OFF")

    # Tray: best effort. If it crashes, keep hotkeys alive.
    if run_tray is None:
        print("  Tray: unavailable (missing backend). Hotkeys only.")
    else:
        print("  Tray: Toggle / ON / OFF / Quit")
        try:
            # Prefer tray in a background thread; keep main thread alive either way.
            t_tray = threading.Thread(target=run_tray, args=(state, stop), daemon=True)
            t_tray.start()
        except Exception as e:
            print(f"[WavePunkOS] Tray failed: {e}. Hotkeys only.")

    # Keep process alive until killed
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop.set()
        print("\n[WavePunkOS] exiting")


if __name__ == "__main__":
    main()
