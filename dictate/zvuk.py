"""Tisina dok se snima: utisan racunar i pauzirana muzika ili video.

Dve odvojene opcije, jer ne resavaju isto:

  utisaj_zvuk        utisa ceo racunar. Jedino sto radi i za poziv, koji ne
                     moze da se pauzira.
  pauziraj_plejer    pauzira ono sto svira (YouTube, Spotify, Muzika), pa
                     posle snimanja nastavlja odakle je stalo.

Taster za pauzu je PREKIDAC: kad nista ne svira, on bi pokrenuo poslednju
aplikaciju (najcesce Muziku). Zato se salje samo kad je sigurno da nesto
svira, i vraca se samo ako ga je Diktat poslao:

  samostalni plejer  taster ⏯, kad CoreAudio kaze da upravo pusta zvuk.
  Google Chrome      BEZ tastera: JavaScript u kartici pauzira samo medij
                     koji zaista svira i obelezi ga, a na kraju nastavi samo
                     obelezen. Taster je tu POKRETAO pauziran video
                     (27.09.2026): Chrome drzi izlaz otvoren i posle pauze,
                     a oznaku kartice „Audio playing" jos ~2 s, pa je video
                     pauziran neposredno pred diktat izgledao kao da svira.
                     Oznaka ostaje kao brz filter: JavaScript ide samo u
                     kartice koje je nose. Trazi „Allow JavaScript from Apple
                     Events" u Chrome-u i dozvolu da Diktat upravlja Chrome-om.
  ostali pregledaci  nemaju pouzdan znak, pa se ne pauziraju.

Vracanje kasni `ODLOZENO_VRACANJE`: kod brzog niza diktata video i zvuk bi se
inace pustali izmedju svaka dva snimka.

Sve ide kroz jednu radnu nit, redom: `osascript` traje ~0,4 s i ne sme da
zadrzi pocetak snimanja, a vracanje ne sme da pretekne utisavanje.
"""

import concurrent.futures
import ctypes
import ctypes.util
import struct
import subprocess
import threading
import time

import AppKit
import Quartz

# Samostalni plejeri: zatvore izlaz kad stanu, pa otvoren izlaz znaci da
# sviraju. Pocetak identifikatora je dovoljan.
PLEJERI = (
    "com.spotify.client", "com.apple.Music", "com.apple.TV",
    "com.apple.podcasts", "org.videolan.vlc", "com.colliderli.iina",
    "com.apple.QuickTimePlayerX", "com.tidal.desktop", "com.deezer",
)
# Pregledaci na Chromium-u: zvuk pusta pomocni proces (`com.google.Chrome.helper`),
# a da li svira se cita iz naziva kartice. Mala slova, jer Arc pise helper
# kao `company.thebrowser.browser.helper`.
CHROMIUM = (
    "com.google.chrome", "com.brave.browser", "com.microsoft.edgemac",
    "company.thebrowser.browser", "com.operasoftware.opera", "com.vivaldi.vivaldi",
)
# Chromium dodaje ovo nazivu kartice (IDS_TAB_AX_LABEL_AUDIO_PLAYING_FORMAT).
ZVUK_U_KARTICI = ("Audio playing",)

NX_KEYTYPE_PLAY = 16
POSLE_PAUZE = 0.15   # da plejer stigne da stane pre nego sto mikrofon krene
ODLOZENO_VRACANJE = 2.0  # novi diktat u ovom roku zatice sve jos pauzirano

# Pauzira samo ono sto svira i obelezi ga; vraca broj pauziranih.
PAUZA_JS = (
    "(function(){var n=0;document.querySelectorAll('video,audio').forEach("
    "function(m){if(!m.paused&&!m.ended){m.pause();m.dataset.diktatPauza='1';n++;}});"
    "return n;})()"
)
# Nastavlja samo ono sto je Diktat pauzirao i sto je i dalje pauzirano.
NASTAVI_JS = (
    "(function(){document.querySelectorAll('video,audio').forEach(function(m){"
    "if(m.dataset.diktatPauza){delete m.dataset.diktatPauza;if(m.paused){m.play();}}});"
    "})()"
)


def _fcc(kod: str) -> int:
    return struct.unpack(">I", kod.encode())[0]


class _Adresa(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32),
                ("element", ctypes.c_uint32)]


_ca = None
_cf = None


def _biblioteke():
    global _ca, _cf
    if _ca is None:
        _ca = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreAudio"))
        _cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        ptr = ctypes.POINTER
        _ca.AudioObjectGetPropertyDataSize.argtypes = [
            ctypes.c_uint32, ptr(_Adresa), ctypes.c_uint32, ctypes.c_void_p,
            ptr(ctypes.c_uint32)]
        _ca.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32, ptr(_Adresa), ctypes.c_uint32, ctypes.c_void_p,
            ptr(ctypes.c_uint32), ctypes.c_void_p]
        _cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                           ctypes.c_long, ctypes.c_uint32]
        _cf.CFRelease.argtypes = [ctypes.c_void_p]
    return _ca, _cf


def _svojstvo(objekat: int, kod: str, tip):
    ca, _ = _biblioteke()
    adresa = _Adresa(_fcc(kod), _fcc("glob"), 0)
    vrednost = tip()
    velicina = ctypes.c_uint32(ctypes.sizeof(vrednost))
    greska = ca.AudioObjectGetPropertyData(
        objekat, ctypes.byref(adresa), 0, None, ctypes.byref(velicina),
        ctypes.byref(vrednost))
    return None if greska else vrednost


def ko_pusta_zvuk() -> list[str]:
    """Identifikatori aplikacija koje upravo salju zvuk na izlaz.

    Trazi macOS 14.2 ili noviji (spisak procesa u CoreAudio). Na starijem
    vraca prazno, pa se pauza jednostavno ne salje.
    """
    ca, cf = _biblioteke()
    adresa = _Adresa(_fcc("prs#"), _fcc("glob"), 0)
    velicina = ctypes.c_uint32()
    if ca.AudioObjectGetPropertyDataSize(1, ctypes.byref(adresa), 0, None,
                                         ctypes.byref(velicina)):
        return []
    procesi = (ctypes.c_uint32 * (velicina.value // 4))()
    if ca.AudioObjectGetPropertyData(1, ctypes.byref(adresa), 0, None,
                                     ctypes.byref(velicina), procesi):
        return []
    pustaju = []
    for proces in procesi:
        izlaz = _svojstvo(proces, "piro", ctypes.c_uint32)
        if izlaz is None or not izlaz.value:
            continue
        ime = _svojstvo(proces, "pbid", ctypes.c_void_p)
        if ime is None or not ime.value:
            continue
        bafer = ctypes.create_string_buffer(512)
        cf.CFStringGetCString(ime, bafer, 512, 0x08000100)   # UTF-8
        cf.CFRelease(ime)
        pustaju.append(bafer.value.decode("utf-8", "replace"))
    return pustaju


def _ax(element, ime):
    from ApplicationServices import AXUIElementCopyAttributeValue
    greska, vrednost = AXUIElementCopyAttributeValue(element, ime, None)
    return vrednost if greska == 0 else None


def _kartice(element, dubina=0):
    """Nazivi kartica u prozoru; sadrzaj stranice se ne obilazi (sporo)."""
    if dubina > 14:
        return
    uloga = _ax(element, "AXRole")
    if uloga == "AXWebArea":
        return
    if _ax(element, "AXSubrole") == "AXTabButton":
        yield str(_ax(element, "AXTitle") or _ax(element, "AXDescription") or "")
        return
    for dete in _ax(element, "AXChildren") or []:
        yield from _kartice(dete, dubina + 1)


def zvucne_kartice(oznaka_aplikacije="com.google.chrome") -> list[str]:
    """Accessibility nazivi kartica koje nose „Audio playing"."""
    from ApplicationServices import AXUIElementCreateApplication
    nadjene = []
    for aplikacija in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        if str(aplikacija.bundleIdentifier() or "").lower() != oznaka_aplikacije:
            continue
        koren = AXUIElementCreateApplication(aplikacija.processIdentifier())
        for prozor in _ax(koren, "AXWindows") or []:
            nadjene += [n for n in _kartice(prozor)
                        if any(z in n for z in ZVUK_U_KARTICI)]
    return nadjene


def svira_plejer(pustaju: list[str]) -> bool:
    """Samostalni plejer koji upravo pusta zvuk (za taster ⏯)."""
    return any(ime.startswith(PLEJERI) for ime in pustaju)


def chrome_pusta(pustaju: list[str]) -> bool:
    return any(ime.lower().startswith("com.google.chrome") for ime in pustaju)


def _as_tekst(tekst: str) -> str:
    return '"' + tekst.replace("\\", "\\\\").replace('"', '\\"') + '"'


def chrome_pauziraj(kartice: list[str]) -> list[str]:
    """Pauziraj medij koji svira u tim karticama; vrati „prozor:kartica".

    Accessibility naziv kartice pocinje naslovom stranice, pa se kartica
    prepoznaje po tome. JavaScript sam proverava da li medij zaista svira.
    """
    if not kartice:
        return []
    spisak = "{" + ", ".join(_as_tekst(k) for k in kartice) + "}"
    skripta = f'''
tell application "Google Chrome"
  set nadjeno to {{}}
  repeat with w in windows
    repeat with t in tabs of w
      set naslov to title of t
      if naslov is not "" then
        repeat with a in {spisak}
          if (a as text) starts with naslov then
            set n to (execute t javascript {_as_tekst(PAUZA_JS)}) as text
            if n is not "0" then set end of nadjeno to ((id of w) as text) & ":" & ((id of t) as text)
            exit repeat
          end if
        end repeat
      end if
    end repeat
  end repeat
  set AppleScript's text item delimiters to ","
  return nadjeno as text
end tell'''
    rezultat = subprocess.run(["osascript", "-e", skripta], capture_output=True,
                              text=True, timeout=10)
    if rezultat.returncode != 0:
        # Najcesce: u Chrome-u iskljuceno „Allow JavaScript from Apple
        # Events", ili macOS ne dozvoljava Diktatu da upravlja Chrome-om.
        raise RuntimeError("Chrome: " + (rezultat.stderr.strip() or "nepoznata greska"))
    return [x for x in rezultat.stdout.strip().split(",") if ":" in x]


def chrome_nastavi(pauzirane: list[str]):
    delovi = []
    for par in pauzirane:
        prozor, kartica = par.split(":", 1)
        if prozor.isdigit() and kartica.isdigit():
            delovi.append(
                f"try\n  execute (first tab of (first window whose id is {prozor}) "
                f"whose id is {kartica}) javascript {_as_tekst(NASTAVI_JS)}\nend try")
    if delovi:
        skripta = 'tell application "Google Chrome"\n' + "\n".join(delovi) + "\nend tell"
        subprocess.run(["osascript", "-e", skripta], capture_output=True,
                       text=True, timeout=10)


def _taster_pauze():
    """Isti dogadjaj koji salje taster ⏯ na tastaturi."""
    for pritisnut in (True, False):
        stanje = 0xA if pritisnut else 0xB
        dogadjaj = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            AppKit.NSEventTypeSystemDefined, (0, 0), stanje << 8, 0, 0, None, 8,
            (NX_KEYTYPE_PLAY << 16) | (stanje << 8), -1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, dogadjaj.CGEvent())


def _osascript(skripta: str) -> str:
    rezultat = subprocess.run(["osascript", "-e", skripta], capture_output=True,
                              text=True, timeout=5)
    return rezultat.stdout.strip()


def utisan() -> bool:
    return _osascript("output muted of (get volume settings)") == "true"


def postavi_utisan(da: bool):
    _osascript(f"set volume output muted {'true' if da else 'false'}")


class Tisina:
    """Pamti sta je Diktat promenio, da vrati samo to i nista drugo."""

    def __init__(self):
        self._nit = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()
        self._utisao = False
        self._pauzirao = False
        self._chrome: list[str] = []   # kartice koje je Diktat pauzirao
        self._red = 0                  # novi diktat ponistava zakazano vracanje
        # Zasebna brava: `pocni` se zove sa puta pokretanja snimanja i ne sme
        # da ceka radnu nit, koja pod `_lock` ume da ceka Chrome i sekundama.
        self._red_lock = threading.Lock()

    def pocni(self, cfg):
        with self._red_lock:
            self._red += 1
        utisaj = bool(cfg.get("utisaj_zvuk", False))
        pauziraj = bool(cfg.get("pauziraj_plejer", False))
        if utisaj or pauziraj:
            self._nit.submit(self._pocni, utisaj, pauziraj)

    def vrati(self):
        """Vrati posle `ODLOZENO_VRACANJE`, osim ako novi diktat krene pre toga."""
        with self._red_lock:
            self._red += 1
            moj = self._red
        tajmer = threading.Timer(
            ODLOZENO_VRACANJE, lambda: self._nit.submit(self._vrati_ako, moj))
        tajmer.daemon = True
        tajmer.start()

    def _vrati_ako(self, moj: int):
        with self._red_lock:
            if moj != self._red:
                return
        self._vrati()

    def vrati_odmah(self):
        """Pri gasenju aplikacije: bez cekanja reda, koji mozda nece ni stici."""
        self._vrati()

    def _pocni(self, utisaj: bool, pauziraj: bool):
        with self._lock:
            self._pocni_zakljucano(utisaj, pauziraj)

    def _pocni_zakljucano(self, utisaj: bool, pauziraj: bool):
        try:
            if pauziraj:
                pustaju = ko_pusta_zvuk()
                if not self._pauzirao and svira_plejer(pustaju):
                    _taster_pauze()
                    self._pauzirao = True
                    time.sleep(POSLE_PAUZE)
                if chrome_pusta(pustaju):
                    try:
                        self._chrome += [k for k in chrome_pauziraj(zvucne_kartice())
                                         if k not in self._chrome]
                    except Exception as exc:  # noqa: BLE001
                        print(f"[diktat] pauza u Chrome-u nije uspela: {exc}", flush=True)
            # Vec utisan racunar se ne dira, pa ga ni vracanje ne ukljucuje.
            if utisaj and not self._utisao and not utisan():
                postavi_utisan(True)
                self._utisao = True
        except Exception as exc:  # noqa: BLE001
            print(f"[diktat] utisavanje nije uspelo: {exc}", flush=True)

    def _vrati(self):
        with self._lock:
            utisao, self._utisao = self._utisao, False
            pauzirao, self._pauzirao = self._pauzirao, False
            chrome, self._chrome = self._chrome, []
        try:
            if utisao:
                postavi_utisan(False)
            if pauzirao:
                _taster_pauze()
            if chrome:
                chrome_nastavi(chrome)
        except Exception as exc:  # noqa: BLE001
            print(f"[diktat] vracanje zvuka nije uspelo: {exc}", flush=True)
