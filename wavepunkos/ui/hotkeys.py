from __future__ import annotations
from pynput import keyboard
from wavepunkos.core.control import ControlState
from wavepunkos.core.ipc_state import set_enabled


def run_hotkeys(state: ControlState) -> None:
    """
    Global hotkeys (X11):
    - Ctrl+Alt+Space: Toggle ON/OFF
    - Ctrl+Alt+Esc:   Panic OFF
    """

    pressed = set()

    CTRL_KEYS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
    ALT_KEYS  = {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}

    def is_ctrl():
        return any(k in pressed for k in CTRL_KEYS)

    def is_alt():
        return any(k in pressed for k in ALT_KEYS)

    def on_press(k):
        pressed.add(k)

        if is_ctrl() and is_alt():
            if k == keyboard.Key.space:
                enabled = state.toggle()
                set_enabled(enabled)
                print(f"[WavePunkOS] {'ON' if enabled else 'OFF'} (Ctrl+Alt+Space)")
            elif k == keyboard.Key.esc:
                state.set_enabled(False)
                set_enabled(False)
                print("[WavePunkOS] OFF (PANIC) (Ctrl+Alt+Esc)")

    def on_release(k):
        pressed.discard(k)

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()
