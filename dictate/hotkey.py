"""Globalna detekcija hotkey-a.

Kljucni detalj: desni Command je i dalje obican modifikator. Ako korisnik
drzi desni Cmd i pritisne bilo koji drugi taster (Cmd+V, Cmd+Tab...), to je
precica a ne diktat — sesija se tada otkazuje i nista se ne ubacuje.
Taster se nikad ne guta, pa sve sistemske precice rade normalno.
"""

import threading
import time

from pynput import keyboard

KEY_MAP = {
    "cmd_r": keyboard.Key.cmd_r,
    "cmd_l": keyboard.Key.cmd_l,
    "alt_r": keyboard.Key.alt_r,
    "alt_l": keyboard.Key.alt_l,
    "ctrl_r": keyboard.Key.ctrl_r,
    "shift_r": keyboard.Key.shift_r,
    "f13": keyboard.Key.f13,
    "f14": keyboard.Key.f14,
    "f15": keyboard.Key.f15,
}


class HotkeyListener:
    def __init__(self, cfg, on_start, on_stop, on_cancel, is_synthetic=None):
        key_name = cfg.get("hotkey", "cmd_r")
        if key_name not in KEY_MAP:
            raise RuntimeError(
                f"Nepoznat hotkey '{key_name}'. Dozvoljeni: {', '.join(KEY_MAP)}"
            )
        self.target = KEY_MAP[key_name]
        self.mode = cfg.get("mode", "hold")
        self.min_seconds = float(cfg.get("min_seconds", 0.35))

        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        # Vraca True dok aplikacija sama salje tastere (lepljenje teksta).
        self.is_synthetic = is_synthetic or (lambda: False)

        self._lock = threading.Lock()
        self._active = False
        self._contaminated = False
        self._pressed_at = 0.0
        self._listener = None

    def start(self):
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    # ------------------------------------------------------------------

    def _on_press(self, key):
        with self._lock:
            if key == self.target:
                if self.mode == "toggle":
                    if self._active:
                        self._active = False
                        self._fire(self.on_stop)
                    else:
                        self._active = True
                        self._contaminated = False
                        self._pressed_at = time.monotonic()
                        self._start()
                    return
                # hold: ignorisi auto-repeat dok je vec aktivno
                if not self._active:
                    self._active = True
                    self._contaminated = False
                    self._pressed_at = time.monotonic()
                    self._start()
                return

            # Neki drugi taster dok drzimo hotkey => ovo je precica, ne diktat.
            # Osim ako smo ga mi poslali: lepljenje segmenta usred diktata salje
            # Cmd+V, i bez ove provere bi aplikacija otkazala sopstveni diktat.
            if self._active and self.mode == "hold" and not self.is_synthetic():
                self._contaminated = True

    def _on_release(self, key):
        with self._lock:
            if key != self.target or self.mode == "toggle":
                return
            if not self._active:
                return
            self._active = False
            held = time.monotonic() - self._pressed_at
            if self._contaminated:
                self._fire(self.on_cancel, "precica")
            elif held < self.min_seconds:
                self._fire(self.on_cancel, "prekratko")
            else:
                self._fire(self.on_stop)

    def _start(self):
        """Pokreni snimanje; ako aplikacija ne moze (mikrofon jos zauzet),
        vrati _active na False da prekidac ne ostane obrnut."""

        def work():
            if self.on_start() is False:
                with self._lock:
                    self._active = False

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _fire(fn, *args):
        # Callback-e vrtimo van pynput niti da spor poziv ne blokira event tap.
        threading.Thread(target=fn, args=args, daemon=True).start()


def accessibility_granted() -> bool:
    """Da li proces sme da cita globalne tastere (Accessibility dozvola)."""
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:  # noqa: BLE001
        return False
