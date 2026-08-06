"""Ubacivanje prepoznatog teksta u aplikaciju koja je trenutno u fokusu."""

import contextlib
import threading
import time

import AppKit
import Quartz

KVK_ANSI_V = 0x09
KVK_SPACE = 0x31
PASTE_SETTLE = 0.12    # da OS stigne da registruje da je Cmd pusten
TYPE_CHUNK = 20
SYNTHETIC_TAIL = 0.15  # koliko jos drzimo zastavicu da event tap stigne da vidi

# Dok je ovo podignuto, tasteri koji stizu su NASI, ne korisnikovi.
#
# Bez ovoga se aplikacija sama saboterala: kad se segment zalepi dok korisnik
# jos drzi hotkey, sintetickim Cmd+V se okine sopstvena detekcija precice, pa
# se ceo ostatak diktata odbaci kao "ovo je bila precica, ne diktat".
_injecting = threading.Event()


def injecting() -> bool:
    return _injecting.is_set()


@contextlib.contextmanager
def _synthetic():
    _injecting.set()
    try:
        yield
    finally:
        time.sleep(SYNTHETIC_TAIL)
        _injecting.clear()


def get_clipboard() -> str | None:
    pb = AppKit.NSPasteboard.generalPasteboard()
    return pb.stringForType_(AppKit.NSPasteboardTypeString)


def set_clipboard(text: str) -> None:
    pb = AppKit.NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)


def kuca_se(text: str, method: str) -> bool:
    """Ide li tekst kucanjem (bez clipboard-a) ili lepljenjem.

    Podrazumevano („auto") je kucanje: clipboard se tada uopste ne dira, pa se
    ne puni istorijom diktata. Vracanje starog sadrzaja to ne resava — hvataci
    istorije (Raycast, Maccy, Paste) zabelezе svaku izmenu, i pre nego sto se
    stari sadrzaj vrati.

    Izuzetak je tekst sa NOVIM REDOM: kucanje ga salje kao Enter, pa bi u
    caskanju poslalo poruku usred diktata. Takav tekst ide preko clipboard-a.
    """
    if method == "type":
        return True
    if method != "auto":
        return False
    return "\n" not in text


def insert(text: str, method="auto", restore_clipboard=True) -> None:
    if not text:
        return
    if method == "clipboard_only":
        set_clipboard(text)
        return
    if kuca_se(text, method):
        _type_unicode(text)
        return
    _paste(text, restore_clipboard=restore_clipboard)


# ----------------------------------------------------------------------


def _paste(text: str, restore_clipboard=True) -> None:
    previous = get_clipboard() if restore_clipboard else None
    set_clipboard(text)
    time.sleep(PASTE_SETTLE)
    _send_cmd_v()
    if restore_clipboard:
        # Vracamo stari clipboard tek kad ciljna aplikacija zavrsi paste.
        time.sleep(0.45)
        if previous is not None:
            set_clipboard(previous)


def _send_cmd_v() -> None:
    with _synthetic():
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        down = Quartz.CGEventCreateKeyboardEvent(src, KVK_ANSI_V, True)
        up = Quartz.CGEventCreateKeyboardEvent(src, KVK_ANSI_V, False)
        Quartz.CGEventSetFlags(down, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventSetFlags(up, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        time.sleep(0.02)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def razdvoji_rep(text: str):
    """Odvoji razmake sa kraja od ostatka teksta.

    Zavrsni razmak se ne sme poslati kao unicode dogadjaj: kad ostane sam u
    svom komadu, deo aplikacija ga odbaci, pa se sledeci diktat zalepi za
    prethodnu rec. Salje se kao PRAVI taster razmaka, isto kao kad ga covek
    otkuca — to nijedna aplikacija ne tretira posebno.
    """
    telo = text.rstrip(" ")
    return telo, len(text) - len(telo)


def _type_unicode(text: str) -> None:
    """Kuca tekst direktno, bez diranja clipboard-a. Sporije, ali cistije."""
    telo, razmaka = razdvoji_rep(text)
    with _synthetic():
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        for i in range(0, len(telo), TYPE_CHUNK):
            piece = telo[i : i + TYPE_CHUNK]
            for is_down in (True, False):
                evt = Quartz.CGEventCreateKeyboardEvent(src, 0, is_down)
                Quartz.CGEventKeyboardSetUnicodeString(evt, len(piece), piece)
                Quartz.CGEventSetFlags(evt, 0)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
            time.sleep(0.006)
        for _ in range(razmaka):
            for is_down in (True, False):
                evt = Quartz.CGEventCreateKeyboardEvent(src, KVK_SPACE, is_down)
                Quartz.CGEventSetFlags(evt, 0)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
            time.sleep(0.006)
