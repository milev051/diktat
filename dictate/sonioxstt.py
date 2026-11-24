"""Soniox stt-rt-v6: zvuk ide serveru DOK snimanje traje (WebSocket).

Ključ se ne ugrađuje u kod. Traži se redom: `soniox_api_key` u config.json,
pa fajl `~/.config/diktat/soniox_api_key` (chmod 600), da isti fajl korisnik
može da otvori i prepiše ključ u telefon.

Protokol: prva poruka je JSON podešavanje, posle nje binarni PCM komadi,
a prazna poruka označava kraj zvuka. Server vraća `tokens` (konačne i
privremene) i na kraju `finished: true`.
"""

import json
import threading
import time
from pathlib import Path

from .wsock import WebSocket, WebSocketError, WebSocketTimeout

WS_ENDPOINT = "wss://stt-rt.soniox.com/transcribe-websocket"
MODEL = "stt-rt-v6"
KEY_FILE = Path.home() / ".config" / "diktat" / "soniox_api_key"
# Posle kraja zvuka server obično završi za manje od sekunde.
KRAJ_ROK = 15.0


class SonioxError(Exception):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


def enabled(cfg) -> bool:
    return str(cfg.get("transcription_provider", "")).lower() == "soniox"


def key(cfg) -> str:
    k = (cfg.get("soniox_api_key") or "").strip()
    if not k:
        try:
            k = KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            k = ""
    if not k:
        raise SonioxError("Soniox API ključ nije podešen.", retryable=False)
    return k


def setup(cfg, api_key) -> dict:
    return {
        "api_key": api_key,
        "model": MODEL,
        "audio_format": "pcm_s16le",
        "sample_rate": int(cfg.get("sample_rate", 16000)),
        "num_channels": 1,
        "language_hints": ["sr"],
        "enable_language_identification": False,
    }


def _tekst(tokeni) -> str:
    # Kontrolni tokeni (<end>, <fin>) nisu govor.
    return "".join(t.get("text", "") for t in tokeni
                   if not str(t.get("text", "")).startswith("<"))


def recognize_live_stream(komadi, cfg, timeout=20, on_update=None,
                          _ws_factory=WebSocket) -> str:
    """Šalji komade dok stižu; vrati ceo prepis kad server završi."""
    api_key = key(cfg)
    konacni = []
    stanje = {"privremeni": [], "error": None, "kraj": False}
    poslato = threading.Event()

    def prikazi():
        if on_update is None:
            return
        try:
            on_update((_tekst(konacni) + _tekst(stanje["privremeni"])).strip())
        except Exception:
            pass

    try:
        with _ws_factory(WS_ENDPOINT, timeout=timeout) as ws:
            ws.send_json(setup(cfg, api_key))
            ws.set_read_poll_timeout(0.25)

            def citaj():
                rok = None
                try:
                    while True:
                        if poslato.is_set() and rok is None:
                            rok = time.monotonic() + KRAJ_ROK
                        if rok is not None and time.monotonic() > rok:
                            break
                        try:
                            if not ws.wait_readable(0.3):
                                continue
                            poruka = ws.recv_json()
                        except WebSocketTimeout:
                            continue
                        if poruka is None:
                            if ws.close_code not in (None, 1000) and not konacni:
                                raise SonioxError(
                                    f"Soniox je zatvorio vezu: {ws.close_code} {ws.close_reason}".strip())
                            break
                        if poruka.get("error_code") or poruka.get("error_message"):
                            kod = poruka.get("error_code")
                            raise SonioxError(
                                f"Soniox {kod}: {str(poruka.get('error_message'))[:200]}",
                                retryable=kod not in (400, 401, 402, 403))
                        tokeni = poruka.get("tokens") or []
                        konacni.extend(t for t in tokeni if t.get("is_final"))
                        stanje["privremeni"] = [t for t in tokeni if not t.get("is_final")]
                        if tokeni:
                            prikazi()
                        if poruka.get("finished"):
                            stanje["kraj"] = True
                            break
                except Exception as exc:
                    stanje["error"] = exc

            citac = threading.Thread(target=citaj, name="soniox-citac", daemon=True)
            citac.start()
            try:
                for komad in komadi:
                    if stanje["error"] is not None:
                        break
                    if komad:
                        ws.send_bytes(komad)
                if stanje["error"] is None:
                    ws.send_text("")
            finally:
                poslato.set()
            citac.join(KRAJ_ROK + 2)
    except WebSocketError as exc:
        raise SonioxError(f"Soniox: {exc}", exc.retryable) from exc
    if stanje["error"] is not None:
        if isinstance(stanje["error"], SonioxError):
            raise stanje["error"]
        raise SonioxError(f"Soniox: {stanje['error']}") from stanje["error"]
    # Bez `finished` se zadržava ono što je stiglo, uključujući privremeni rep.
    tekst = _tekst(konacni) + ("" if stanje["kraj"] else _tekst(stanje["privremeni"]))
    return tekst.strip()


def recognize(pcm: bytes, cfg, timeout=60) -> str:
    """Ceo snimak odjednom (npr. prepis sačuvanog snimka)."""
    korak = 3200
    return recognize_live_stream(
        (pcm[i:i + korak] for i in range(0, len(pcm), korak)), cfg, timeout=timeout)
