"""Ubacivanje prepoznatog teksta u aplikaciju koja je trenutno u fokusu."""

import contextlib
import threading
import time

import AppKit
import Quartz
import ApplicationServices as AX

from . import webstt

KVK_ANSI_V = 0x09
KVK_DOWN_ARROW = 0x7D
PASTE_SETTLE = 0.12    # da OS stigne da registruje da je Cmd pusten
TYPE_CHUNK = 20
SYNTHETIC_TAIL = 0.15  # koliko jos drzimo zastavicu da event tap stigne da vidi

# Dok je ovo podignuto, tasteri koji stizu su NASI, ne korisnikovi.
#
# Bez ovoga se aplikacija sama saboterala: kad se segment zalepi dok korisnik
# jos drzi hotkey, sintetickim Cmd+V se okine sopstvena detekcija precice, pa
# se ceo ostatak diktata odbaci kao "ovo je bila precica, ne diktat".
_injecting = threading.Event()
_live_field = None
_live_preview_blocked = False
_live_reason = ""
_zadrzi_prikaz = False
_SECURE_INPUT = object()


def _reci(tekst: str) -> list[str]:
    return "".join(
        ch for ch in (tekst or "").casefold() if ch.isalnum() or ch.isspace()
    ).split()


def ostatak_prepisa(vec_u_polju: str, konacan: str) -> str:
    """Vrati samo deo koji još nije upisan.

    Prazan konačan prepis ne briše ono što je korisnik već video.
    Veliko slovo i tačka na kraju ne prave drugi upis istog teksta.
    """
    vec = (vec_u_polju or "").strip()
    cilj = (konacan or "").strip()
    if not cilj:
        return ""
    if not vec:
        return cilj
    if cilj.startswith(vec) and (len(cilj) == len(vec) or cilj[len(vec)].isspace()):
        return cilj[len(vec):].strip()
    reci_vec = _reci(vec)
    reci_cilj = _reci(cilj)
    if reci_cilj[:len(reci_vec)] == reci_vec:
        if len(reci_cilj) == len(reci_vec):
            return ""
        return " ".join(cilj.split()[len(reci_vec):]).strip()
    # Izmenjena reč nije čist nastavak. Već upisani prikaz ostaje;
    # ceo novi tekst bi se pojavio još jednom.
    return ""


def ima_prikaz() -> bool:
    return _live_field is not None


def zadrzi_prikaz() -> None:
    """Stop ne sme da obriše rep koji je korisnik već video u polju."""
    global _zadrzi_prikaz
    _zadrzi_prikaz = True


def live_failure_reason() -> str:
    return _live_reason or "polje nije prihvatilo privremeni tekst"


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


def _agent_desk_active() -> bool:
    """WKWebView Agent Deska dobija pravi DOM unos preko sistemskog paste-a."""
    try:
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return app is not None and app.bundleIdentifier() == "local.agent-desk.launcher"
    except Exception:
        return False


def _input_snapshot():
    """Čita cilj unosa bez zahteva da AX dozvoljava menjanje njegove vrednosti."""
    try:
        root = AX.AXUIElementCreateSystemWide()
        element = _ax_attr(root, AX.kAXFocusedUIElementAttribute)
        if element is None:
            return None
        role = _ax_attr(element, AX.kAXRoleAttribute)
        if role not in (AX.kAXTextFieldRole, AX.kAXTextAreaRole, "AXComboBox", "AXSearchField"):
            return None
        if "Secure" in str(_ax_attr(element, AX.kAXSubroleAttribute) or ""):
            return _SECURE_INPUT
        return element, _ax_value(element)
    except Exception:
        return None


def _remaining(snapshot, text):
    element, before = snapshot
    if before is None:
        # Neka web polja primaju unos, ali ne izlažu sadržaj kroz AX.
        return ""
    after = _ax_value(element)
    if after is None or after == before:
        return text
    prefix = 0
    while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < min(len(before) - prefix, len(after) - prefix)
           and before[len(before) - suffix - 1] == after[len(after) - suffix - 1]):
        suffix += 1
    added = after[prefix:len(after) - suffix if suffix else len(after)]
    return text[len(added):] if added and text.startswith(added) else text


def _deliver(text, action):
    snapshot = _input_snapshot()
    if snapshot is _SECURE_INPUT:
        return False
    # AX može izostati u web editoru koji normalno prima Cmd+V.
    # Nečitljiv cilj nije razlog da preskočimo sam unos.
    action()
    if snapshot is None or snapshot[1] is None:
        return True  # Nema potvrde kroz AX; ne ponavljaj naslepo i ne dupliraj.
    deadline = time.monotonic() + 0.6
    while True:
        rest = _remaining(snapshot, text)
        if not rest:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.03)


def insert(text: str, method="auto", restore_clipboard=True) -> bool:
    text = webstt.glasovne_komande(text)
    if not text:
        return True
    if method == "clipboard_only":
        set_clipboard(text)
        return True
    if method == "auto" and _agent_desk_active():
        return _deliver(text, lambda: _paste(text, restore_clipboard=restore_clipboard))
    if kuca_se(text, method):
        delivered = _deliver(text, lambda: _type_unicode(text))
        if not restore_clipboard:
            set_clipboard(text)
        return delivered
    return _deliver(text, lambda: _paste(text, restore_clipboard=restore_clipboard))


def nalepi_clipboard() -> None:
    """Nalepi ono sto je vec u clipboard-u u polje koje je u fokusu."""
    time.sleep(PASTE_SETTLE)
    _send_cmd_v()


def insert_live(text: str) -> None:
    """Dodaj potvrđenu celinu na kraj aktivnog polja dok korisnik diktira.

    Korisnik može da klikne raniju reč i ispravi je. Pre sledeće celine kursor
    vraćamo na kraj, da nova rečenica ne upadne usred te ispravke.
    """
    text = webstt.glasovne_komande(text)
    if not text:
        return
    global _live_field, _live_preview_blocked
    if _live_field is not None:
        element, preview = _live_field
        _live_field = None
        _live_preview_blocked = False
        focused = _focused_plain_field()
        current = _ax_value(element)
        if focused is not None and focused == element and current is not None:
            replacement = _replace_live_suffix(current, preview, text)
            if replacement is None:
                # Korisnik je promenio nas rep. Njegov unos ima prednost;
                # puna potvrda bi samo ponovila isti govor.
                return
            if replacement is not None and _ax_set(element, replacement):
                return
        # Fokus se promenio: ukloni nas nedovrseni rep iz starog polja, ako ga
        # korisnik nije dirao, pa potvrdeni tekst upisi u trenutno polje.
        if current is not None:
            original = _replace_live_suffix(current, preview, "")
            if original is not None:
                _ax_set(element, original)
    _live_preview_blocked = False
    if _agent_desk_active():
        # Unicode CGEvent i AXValue nisu pouzdan DOM input u WKWebView-u.
        # Ne šalji Cmd+Down: unos ostaje na korisnikovom mestu kursora.
        _deliver(text, lambda: _paste(text))
        return
    if "\n" in text:
        # Kucan prelom stize kao Enter i u caskanju salje poruku, pa ide
        # lepljenjem, na kraj polja kao i ostatak.
        def paste_at_end():
            _type_unicode("", move_to_end=True)
            _paste(text)
        _deliver(text, paste_at_end)
        return
    _deliver(text, lambda: _type_unicode(text, move_to_end=True))


def _replace_live_suffix(current: str, old: str, new: str) -> str | None:
    """Menja samo rep koji smo mi upisali, uz ocuvanje tudjih izmena ispred."""
    if not old or not current.endswith(old):
        return None
    return current[:-len(old)] + new


def _ax_attr(element, name):
    try:
        error, value = AX.AXUIElementCopyAttributeValue(element, name, None)
        return value if error == 0 else None
    except Exception:
        return None


def _ax_value(element) -> str | None:
    value = _ax_attr(element, AX.kAXValueAttribute)
    return value if isinstance(value, str) else None


def _ax_set(element, value: str) -> bool:
    try:
        return AX.AXUIElementSetAttributeValue(element, AX.kAXValueAttribute, value) == 0
    except Exception:
        return False


def _focused_plain_field():
    """Samo obicna tekstualna polja; bogati editori imaju sopstveno formatiranje."""
    global _live_reason
    if _agent_desk_active():
        _live_reason = "Agent Desk: potvrđeni tekst ide standardnim lepljenjem"
        return None
    try:
        if not AX.AXIsProcessTrusted():
            _live_reason = "nema dozvole Pristupačnost"
            return None
        root = AX.AXUIElementCreateSystemWide()
        element = _ax_attr(root, AX.kAXFocusedUIElementAttribute)
        if element is None:
            _live_reason = "nema aktivnog tekstualnog polja"
            return None
        role = _ax_attr(element, AX.kAXRoleAttribute)
        if role not in (AX.kAXTextFieldRole, AX.kAXTextAreaRole):
            _live_reason = f"polje ne podržava direktne izmene ({role or 'nepoznat tip'})"
            return None
        subrole = _ax_attr(element, AX.kAXSubroleAttribute)
        if subrole is not None and "Secure" in str(subrole):
            _live_reason = "zaštićeno polje"
            return None
        error, settable = AX.AXUIElementIsAttributeSettable(
            element, AX.kAXValueAttribute, None
        )
        if error != 0 or not settable:
            _live_reason = "polje ne dozvoljava Accessibility upis"
            return None
        if _ax_value(element) is None:
            _live_reason = "sadržaj polja nije čitljiv"
            return None
        return element
    except Exception:
        _live_reason = "Accessibility pristup polju nije uspeo"
        return None


def preview_live(text: str) -> bool:
    """Privremeni prepis u polju, uz proveru da je prethodni rep netaknut."""
    global _live_field, _live_preview_blocked, _live_reason
    if not text or _live_preview_blocked:
        return False
    focused = _focused_plain_field()
    if focused is None:
        _live_preview_blocked = True
        return False
    current = _ax_value(focused)
    if current is None:
        _live_preview_blocked = True
        _live_reason = "sadržaj polja nije čitljiv"
        return False
    if _live_field is not None:
        element, old = _live_field
        if focused != element:
            _live_preview_blocked = True
            _live_reason = "fokus je prešao u drugo polje"
            return False
        replacement = _replace_live_suffix(current, old, text)
        if replacement is None:
            _live_preview_blocked = True
            _live_reason = "privremeni tekst je izmenjen u polju"
            return False
    else:
        replacement = current + text
    if _ax_set(focused, replacement):
        _live_field = (focused, text)
        return True
    else:
        _live_preview_blocked = True
        _live_reason = "polje je odbilo direktnu izmenu"
        return False


def finish_live() -> None:
    """Ukloni nepotvrdjeni rep ako je diktat otkazan ili je server pao."""
    global _live_field, _live_preview_blocked, _zadrzi_prikaz
    if _zadrzi_prikaz:
        _live_field = None
        _live_preview_blocked = False
        _zadrzi_prikaz = False
        return
    if _live_field is not None:
        element, preview = _live_field
        current = _ax_value(element)
        if current is not None:
            replacement = _replace_live_suffix(current, preview, "")
            if replacement is not None:
                _ax_set(element, replacement)
    _live_field = None
    _live_preview_blocked = False


# ----------------------------------------------------------------------


def _paste(text: str, restore_clipboard=True) -> None:
    # Paste koristi clipboard privremeno; uspešan unos ga ne ostavlja promenjenim.
    pb = AppKit.NSPasteboard.generalPasteboard()
    saved = []
    if restore_clipboard:
        for item in pb.pasteboardItems() or []:
            clone = AppKit.NSPasteboardItem.alloc().init()
            for kind in item.types():
                data = item.dataForType_(kind)
                if data is not None:
                    clone.setData_forType_(data, kind)
            saved.append(clone)
    try:
        set_clipboard(text)
        time.sleep(PASTE_SETTLE)
        _send_cmd_v()
        time.sleep(0.45)
    finally:
        if restore_clipboard:
            pb.clearContents()
            if saved:
                pb.writeObjects_(saved)


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


def komadi(text: str, velicina: int = TYPE_CHUNK) -> list:
    """Podela teksta na komade koji se kucaju.

    Komad koji je SAM razmak se ne salje: deo aplikacija takav dogadjaj odbaci,
    pa se sledeci diktat zalepi za prethodnu rec. Zato se zavrsni razmak spaja
    sa komadom ispred sebe.

    Razmak se pri tom NE salje kao poseban taster: pravi taster i unicode
    dogadjaj idu razlicitim putem kroz sistem, pa je razmak stizao sa
    zakasnjenjem — usred sledece reci („sto" -> „st o") ili udvojen.
    """
    delovi = [text[i : i + velicina] for i in range(0, len(text), velicina)]
    if len(delovi) > 1 and not delovi[-1].strip():
        # Prvo `pop`, pa upis: `delovi[-2] += delovi.pop()` gadja pogresan
        # indeks, jer se lista u medjuvremenu skrati.
        rep = delovi.pop()
        delovi[-1] += rep
    return delovi


def _type_unicode(text: str, move_to_end=False) -> None:
    """Kuca tekst direktno, bez diranja clipboard-a. Sporije, ali cistije."""
    with _synthetic():
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        if move_to_end:
            for is_down in (True, False):
                evt = Quartz.CGEventCreateKeyboardEvent(src, KVK_DOWN_ARROW, is_down)
                Quartz.CGEventSetFlags(evt, Quartz.kCGEventFlagMaskCommand)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
            time.sleep(0.015)
        for piece in komadi(text):
            for is_down in (True, False):
                evt = Quartz.CGEventCreateKeyboardEvent(src, 0, is_down)
                Quartz.CGEventKeyboardSetUnicodeString(evt, len(piece), piece)
                Quartz.CGEventSetFlags(evt, 0)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
            time.sleep(0.006)
