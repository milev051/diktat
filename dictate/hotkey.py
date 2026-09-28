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

Dugme misa (srednje ili bocno) moze da bude jos jedan prekidac. Ne bira se sa
spiska nego se snima: `snimi_dugme` ceka sledeci pritisak dugmeta i pamti broj
koji macOS zaista salje (Logi Options+ ume bocno dugme da posalje kao srednje).
Izabrano dugme se guta, inace bi srednji klik otvarao linkove, a bocno vracalo
stranicu nazad. Zato i mis ide kroz aktivan tap, ali samo za ta dugmad i samo
kad je dugme izabrano ili se snima.
"""

import contextlib
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

try:                       # tap za dugmad misa; bez njega mis otpada
    from Quartz import (
        CFMachPortCreateRunLoopSource,
        CFRunLoopAddSource,
        CFRunLoopGetCurrent,
        CFRunLoopRun,
        CFRunLoopStop,
        CGEventMaskBit,
        CGEventTapCreate,
        CGEventTapEnable,
        kCFRunLoopCommonModes,
        kCGEventOtherMouseDown,
        kCGEventOtherMouseUp,
        kCGEventTapDisabledByTimeout,
        kCGEventTapDisabledByUserInput,
        kCGEventTapOptionDefault,
        kCGHeadInsertEventTap,
        kCGMouseEventButtonNumber,
        kCGSessionEventTap,
    )
except Exception:          # noqa: BLE001
    CGEventTapCreate = None

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


def _zakucaj_raspored():
    """Procitaj raspored tastature jednom, na glavnoj niti.

    pynput ga cita (TIS/TSM iz HIToolbox-a) u svojoj niti pri svakom pokretanju
    osluskivaca. Dok aplikacija vec radi, macOS to obara (SIGTRAP u
    `dispatch_assert_queue`, izmereno 28.09.2026 na „Isključi" za dugme misa).
    Raspored sluzi samo za prevod koda tastera u znak, a prekidace poredimo po
    `vk` i po `Key`, pa zapamcena vrednost ne smeta ni kad se raspored promeni.
    """
    try:
        from pynput._util import darwin as util_darwin
        from pynput.keyboard import _darwin as keyboard_darwin
    except Exception:  # noqa: BLE001 — nije macOS
        return
    if getattr(keyboard_darwin, "_diktat_raspored", False):
        return
    if threading.current_thread() is not threading.main_thread():
        return
    with util_darwin.keycode_context() as raspored:
        pass

    @contextlib.contextmanager
    def zapamcen():
        yield raspored

    keyboard_darwin.keycode_context = zapamcen
    keyboard_darwin._diktat_raspored = True


def naziv_dugmeta(broj) -> str:
    """Quartz broji od nule: 2 je srednje dugme, 3 i 4 su uobicajena bocna."""
    if broj is None:
        return "isključeno"
    if broj == 2:
        return "srednje dugme miša"
    return f"dugme miša {broj + 1}"


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

        broj = cfg.get("mouse_button")
        self.mouse_button = broj if isinstance(broj, int) and 2 <= broj <= 31 else None
        self._ucenje = None           # callback dok se ceka dugme za snimanje
        self._progutaj_pustanje = None
        self._mis_tap = None
        self._mis_petlja = None
        self._mis_nit = None
        self._mis_zaustavljen = False

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
        _zakucaj_raspored()
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,
            **dodatno,
        )
        self._listener.daemon = True
        self._listener.start()
        if self.mouse_button is not None:
            self._pokreni_mis()

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
        self._mis_zaustavljen = True
        self._ucenje = None
        if self._mis_tap is not None:
            CGEventTapEnable(self._mis_tap, False)
        if self._mis_petlja is not None:
            CFRunLoopStop(self._mis_petlja)

    # ------------------------------------------------------------ mis

    def snimi_dugme(self, gotovo):
        """Sledeci pritisak srednjeg ili bocnog dugmeta postaje prekidac.

        `gotovo(broj)` se zove van tap niti; cuvanje u config je na pozivaocu.
        """
        self._ucenje = gotovo
        self._pokreni_mis()
        return self._mis_nit is not None

    def otkazi_snimanje(self):
        self._ucenje = None

    def iskljuci_dugme(self):
        """Tap ostaje, ali vise nista ne guta; pynput se ne pokrece iznova."""
        self._ucenje = None
        self.mouse_button = None

    def _pokreni_mis(self):
        if self._mis_nit is not None or CGEventTapCreate is None:
            return

        def rad():
            maska = CGEventMaskBit(kCGEventOtherMouseDown) | CGEventMaskBit(kCGEventOtherMouseUp)
            tap = CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap,
                                   kCGEventTapOptionDefault, maska, self._mis_dogadjaj, None)
            if tap is None:        # nema Accessibility dozvole
                return
            self._mis_tap = tap
            izvor = CFMachPortCreateRunLoopSource(None, tap, 0)
            self._mis_petlja = CFRunLoopGetCurrent()
            CFRunLoopAddSource(self._mis_petlja, izvor, kCFRunLoopCommonModes)
            CGEventTapEnable(tap, True)
            if not self._mis_zaustavljen:
                CFRunLoopRun()

        self._mis_nit = threading.Thread(target=rad, daemon=True)
        self._mis_nit.start()

    def _mis_dogadjaj(self, _proxy, tip, event, _refcon):
        """Vrati None da dugme nestane; sve ostalo prosledi netaknuto."""
        if tip in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            if self._mis_tap is not None and not self._mis_zaustavljen:
                CGEventTapEnable(self._mis_tap, True)
            return event
        try:
            broj = int(CGEventGetIntegerValueField(event, kCGMouseEventButtonNumber))
        except Exception:  # noqa: BLE001 — mis ne sme da stane zbog nas
            return event
        if tip == kCGEventOtherMouseDown:
            gotovo, self._ucenje = self._ucenje, None
            if gotovo is not None:
                self.mouse_button = broj
                self._progutaj_pustanje = broj
                self._fire(gotovo, broj)
                return None
            if broj == self.mouse_button:
                with self._lock:
                    self._pritisak()
                return None
        elif tip == kCGEventOtherMouseUp:
            if broj == self._progutaj_pustanje:
                self._progutaj_pustanje = None
                return None
            if broj == self.mouse_button:
                with self._lock:
                    self._pustanje()
                return None
        return event

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
                self._pritisak()
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
            if self._matches(key):
                self._pustanje()

    def _pritisak(self):
        """Prekidac pritisnut (taster ili dugme misa); zove se pod `_lock`."""
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

    def _pustanje(self):
        """Prekidac pusten; znacajno samo u rezimu „drzi taster"."""
        if self.mode == "toggle" or not self._active:
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
