"""Ubacivanje prepoznatog teksta u aplikaciju koja je trenutno u fokusu."""

import contextlib
import threading
import time

import AppKit
import Quartz

KVK_ANSI_V = 0x09
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


def insert(text: str, method="paste", restore_clipboard=True) -> None:
    if not text:
        return
    if method == "clipboard_only":
        set_clipboard(text)
        return
    if method == "type":
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


def _type_unicode(text: str) -> None:
    """Kuca tekst direktno, bez diranja clipboard-a. Sporije, ali cistije."""
    with _synthetic():
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        for i in range(0, len(text), TYPE_CHUNK):
            piece = text[i : i + TYPE_CHUNK]
            for is_down in (True, False):
                evt = Quartz.CGEventCreateKeyboardEvent(src, 0, is_down)
                Quartz.CGEventKeyboardSetUnicodeString(evt, len(piece), piece)
                Quartz.CGEventSetFlags(evt, 0)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
            time.sleep(0.006)
