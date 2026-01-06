from __future__ import annotations

import threading
import time

import pystray
from PIL import Image, ImageDraw

from wavepunkos.core.control import ControlState


def _make_icon(enabled: bool) -> Image.Image:
    # Minimal monochrome dot icon (small, subtle)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # outer ring
    d.ellipse((16, 16, 48, 48), outline=(255, 255, 255, 220), width=3)

    # inner dot indicates ON/OFF
    dot = (255, 255, 255, 255) if enabled else (255, 255, 255, 80)
    d.ellipse((28, 28, 36, 36), fill=dot)
    return img


def run_tray(state: ControlState, stop_flag: threading.Event) -> None:
    icon = pystray.Icon("WavePunkOS")

    def update_icon():
        icon.icon = _make_icon(state.is_enabled())
        icon.title = f"WavePunkOS ({'ON' if state.is_enabled() else 'OFF'})"

    def on_toggle(_icon, _item):
        state.toggle()
        update_icon()

    def on_off(_icon, _item):
        state.set_enabled(False)
        update_icon()

    def on_on(_icon, _item):
        state.set_enabled(True)
        update_icon()

    def on_quit(_icon, _item):
        stop_flag.set()
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem("Toggle (ON/OFF)", on_toggle),
        pystray.MenuItem("Turn ON", on_on),
        pystray.MenuItem("Turn OFF", on_off),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    update_icon()

    # background updater keeps icon state fresh even if hotkeys toggle it
    def watcher():
        last = None
        while not stop_flag.is_set():
            cur = state.is_enabled()
            if cur != last:
                update_icon()
                last = cur
            time.sleep(0.2)

    threading.Thread(target=watcher, daemon=True).start()
    try:
        icon.run()
    except Exception as e:
        # Tray backends can be fragile; do not kill the app.
        print(f"[WavePunkOS] Tray backend crashed: {e}")
        stop_flag.set()
