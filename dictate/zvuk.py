"""Tisina dok se snima: utisan racunar i pauzirana muzika ili video.

Dve odvojene opcije, jer ne resavaju isto:

  utisaj_zvuk        utisa ceo racunar. Jedino sto radi i za poziv, koji ne
                     moze da se pauzira.
  pauziraj_plejer    pauzira ono sto svira (YouTube, Spotify, Muzika), pa
                     posle snimanja nastavlja odakle je stalo.

Taster za pauzu je PREKIDAC: kad nista ne svira, on bi pokrenuo poslednju
aplikaciju (najcesce Muziku). Zato se salje samo kad CoreAudio kaze da neka
aplikacija za muziku ili video upravo pusta zvuk, i vraca se samo ako ga je
Diktat poslao.

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

# Aplikacije koje reaguju na taster za pauzu. Pocetak identifikatora je
# dovoljan: Chrome pusta zvuk iz `com.google.Chrome.helper`, Safari iz
# `com.apple.WebKit.GPU`.
PLEJERI = (
    "com.google.Chrome", "com.apple.Safari", "com.apple.WebKit",
    "org.mozilla.firefox", "company.thebrowser", "com.microsoft.edgemac",
    "com.brave.Browser", "com.operasoftware", "com.vivaldi.Vivaldi",
    "com.spotify.client", "com.apple.Music", "com.apple.TV",
    "com.apple.podcasts", "org.videolan.vlc", "com.colliderli.iina",
    "com.apple.QuickTimePlayerX", "com.tidal.desktop", "com.deezer",
)

NX_KEYTYPE_PLAY = 16
POSLE_PAUZE = 0.15   # da plejer stigne da stane pre nego sto mikrofon krene


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


def svira_plejer(pustaju: list[str]) -> bool:
    return any(ime.startswith(PLEJERI) for ime in pustaju)


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

    def pocni(self, cfg):
        utisaj = bool(cfg.get("utisaj_zvuk", False))
        pauziraj = bool(cfg.get("pauziraj_plejer", False))
        if utisaj or pauziraj:
            self._nit.submit(self._pocni, utisaj, pauziraj)

    def vrati(self):
        self._nit.submit(self._vrati)

    def vrati_odmah(self):
        """Pri gasenju aplikacije: bez cekanja reda, koji mozda nece ni stici."""
        self._vrati()

    def _pocni(self, utisaj: bool, pauziraj: bool):
        with self._lock:
            self._pocni_zakljucano(utisaj, pauziraj)

    def _pocni_zakljucano(self, utisaj: bool, pauziraj: bool):
        try:
            if pauziraj and not self._pauzirao and svira_plejer(ko_pusta_zvuk()):
                _taster_pauze()
                self._pauzirao = True
                time.sleep(POSLE_PAUZE)
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
        try:
            if utisao:
                postavi_utisan(False)
            if pauzirao:
                _taster_pauze()
        except Exception as exc:  # noqa: BLE001
            print(f"[diktat] vracanje zvuka nije uspelo: {exc}", flush=True)
