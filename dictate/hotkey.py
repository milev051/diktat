"""Globalna detekcija hotkey-a.

Kljucni detalj: desni Command je i dalje obican modifikator. Ako korisnik
drzi desni Cmd i pritisne bilo koji drugi taster (Cmd+V, Cmd+Tab...), to je
precica a ne diktat — sesija se tada otkazuje i nista se ne ubacuje.
Modifikator se nikad ne guta, pa sve sistemske precice rade normalno.

Izuzetak su `§` (levo od jedinice na ISO tastaturi) i `` ` `` (levo od Z,
pored levog Shift-a). Oni nisu modifikatori nego obicni znakovi, pa bi pri
svakom diktatu ostavljali znak u tekstu. Zato se, i samo dok su izabrani kao
prekidac, gutaju preko `darwin_intercept`. Gutanje trazi AKTIVAN event tap:
dogadjaji tastature tada prolaze kroz nas proces, pa se ukljucuje samo kad je
bar jedna od tih opcija upaljena. Uz modifikator (Shift+§ = „±", Shift+` = „~",
Cmd+§) ne guta se nista i taster radi kao i pre.
"""

import threading
import time

from pynput import keyboard

try:                       # samo macOS; bez Quartz-a gutanje otpada
    from Quartz import (
        CGEventGetFlags,
        CGEventGetIntegerValueField,
        kCGEventFlagMaskAlternate,
        kCGEventFlagMaskCommand,
        kCGEventFlagMaskControl,
        kCGEventFlagMaskShift,
        kCGKeyboardEventKeycode,
    )
    MOD_MASK = (
        kCGEventFlagMaskCommand | kCGEventFlagMaskShift
        | kCGEventFlagMaskAlternate | kCGEventFlagMaskControl
    )
except Exception:          # noqa: BLE001
    CGEventGetFlags = None
    MOD_MASK = 0

# kVK_ISO_Section: taster levo od „1" na ISO rasporedu.
SECTION_VK = 10
# kVK_ANSI_Grave: taster „`"; na ISO rasporedu stoji levo od Z.
GRAVE_VK = 50

# Modifikatori koji, kad se drze, znace da „§" nije prekidac nego deo precice.
MODIFIER_KEYS = {
    keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
    keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
    keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
    keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
}


def is_section_key(key) -> bool:
    """Da li je pritisnut `§`; `vk` je pouzdaniji od znaka, koji zavisi od rasporeda."""
    return getattr(key, "vk", None) == SECTION_VK

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
        self.cfg = cfg
        self.target = KEY_MAP[key_name]
        self.mode = cfg.get("mode", "toggle")
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
        self._mods = set()

    def znak_tasteri(self) -> set:
        """`vk` tastera-znakova koji su trenutno prekidac; jedino njih gutamo."""
        vks = set()
        if self.cfg.get("hotkey_section", True):
            vks.add(SECTION_VK)
        if self.cfg.get("hotkey_grave", False):
            vks.add(GRAVE_VK)
        return vks

    def start(self):
        # Aktivan tap (preko `darwin_intercept`) se pravi SAMO kad se `§` ili
        # `` ` `` zaista koristi: tada svaki taster prolazi kroz nas proces.
        dodatno = (
            {"darwin_intercept": self._intercept}
            if self.znak_tasteri() and CGEventGetFlags is not None else {}
        )
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,
            **dodatno,
        )
        self._listener.daemon = True
        self._listener.start()

    def _intercept(self, _event_type, event):
        """Vrati None da dogadjaj nestane; sve ostalo prosledi netaknuto."""
        try:
            if (
                CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                in self.znak_tasteri()
                and not (CGEventGetFlags(event) & MOD_MASK)
            ):
                return None
        except Exception:  # noqa: BLE001 — tastatura ne sme da stane zbog nas
            pass
        return event

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    # ------------------------------------------------------------------

    def _matches(self, key) -> bool:
        """Prekidac je izabrani modifikator, a uz opcije i `§` / `` ` `` bez modifikatora."""
        if key == self.target:
            return True
        return (
            getattr(key, "vk", None) in self.znak_tasteri()
            and not self._mods
        )

    def _on_press(self, key):
        with self._lock:
            if key in MODIFIER_KEYS:
                self._mods.add(key)
            if self._matches(key):
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
            # Modifikator se skida PRE poredjenja: „§" pusten posle Shift-a ne
            # sme da ostane zapamcen kao precica.
            if key in MODIFIER_KEYS:
                self._mods.discard(key)
            if not self._matches(key) or self.mode == "toggle":
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

    def reset(self, pokrenuto=None):
        """Vrati prekidac u mirovanje.

        Zove se kad se snimanje samo prekine na granici: bez toga bi prekidac
        ostao "aktivan" pa bi sledeci pritisak radio STOP umesto START, i
        korisnik bi morao dvaput.

        `pokrenuto` je trenutak kad je snimanje koje se oslobadja pocelo.
        Pritisak POSLE toga pripada novom snimanju (krenuo si dok je rep
        prethodnog jos trajao) i ne sme da se obrise: novo snimanje bi teklo
        dok prekidac misli da ne snima, pa bi svaki sledeci pritisak bio START
        koji ne dobije mikrofon, a snimanje ne bi stalo do granice.
        """
        with self._lock:
            if pokrenuto is not None and self._pressed_at > pokrenuto:
                return
            self._active = False
            self._contaminated = False
            self._mods.clear()

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
