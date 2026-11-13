"""Kratak, oprezan opis uzroka neuspele transkripcije."""

import datetime
import threading
import time
from collections import deque
from pathlib import Path


LIVE_LOG = Path.home() / "Library/Logs/Diktat-live.log"


class LiveTrace:
    """Vremena prijema, slanja i upisa; bez zvuka, prepisa i API ključa."""

    def __init__(self, session: int, path: Path = LIVE_LOG):
        self.session = session
        self.path = path
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self._recent = deque(maxlen=4)
        self.last_audio = None
        self.first_audio = None
        self.last_response = None
        self.sending_since = None
        self.sent_bytes = 0
        self._last_audio_report = 0.0
        self._last_skip = ""
        self.mark("start")

    def mark(self, kind: str, value=0):
        now = time.monotonic()
        with self._lock:
            if kind == "send_start":
                self.sending_since = now
                return
            if kind == "send_done":
                duration = now - (self.sending_since or now)
                self.sending_since = None
                self.last_audio = now
                if self.first_audio is None:
                    self.first_audio = now
                self.sent_bytes += int(value)
                if now - self._last_audio_report < 1.0 and duration < 0.5:
                    return
                self._last_audio_report = now
                detail = f"{self.sent_bytes // 1024} KB poslato, slanje {duration:.2f}s"
            elif kind in ("interim", "final"):
                self.last_response = now
                detail = f"{int(value)} znakova"
            elif kind == "field_ok":
                self._last_skip = ""
                detail = f"upis {float(value):.2f}s od prijema"
            elif kind == "field_skip":
                detail = str(value)[:90]
                if detail == self._last_skip:
                    return
                self._last_skip = detail
            elif kind == "queue_wait":
                detail = f"čekanje {float(value):.2f}s"
            elif kind == "socket_lock_wait":
                detail = f"čitač zadržao vezu {float(value):.2f}s"
            else:
                detail = str(value)[:90] if value else ""
            elapsed = now - self.started
            label = {
                "start": "Diktat pokrenut",
                "connecting": "Povezivanje sa Gemini",
                "connected": "Gemini veza otvorena",
                "tcp_ready": "TCP veza otvorena",
                "tls_ready": "TLS zaštita spremna",
                "websocket_ready": "WebSocket spreman",
                "socket_lock_wait": "Lokalno čekanje WebSocket veze",
                "send_done": "Zvuk poslat",
                "interim": "Privremeni prepis stigao",
                "final": "Potvrđeni prepis stigao",
                "field_ok": "Upis u polje",
                "field_skip": "Upis u polje preskočen",
                "field_final": "Potvrđeni deo predat polju",
                "queue_wait": "Red za upis kasni",
                "error": "Greška toka",
                "end": "Diktat završen",
            }.get(kind, kind)
            line = f"+{elapsed:05.1f}s {label}" + (f": {detail}" if detail else "")
            self._recent.append(line)
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(f"{stamp} sesija {self.session} {line}\n")
            except OSError:
                pass

    def snapshot(self) -> str:
        now = time.monotonic()
        with self._lock:
            if self.sending_since and now - self.sending_since >= 1.5:
                state = f"Slanje zvuka stoji {now - self.sending_since:.1f}s (mreža ili server)."
            elif self.first_audio and now - (self.last_response or self.first_audio) >= 3.0:
                age = now - (self.last_response or self.first_audio)
                if self.last_audio and now - self.last_audio < 1.5:
                    state = f"Zvuk se šalje; Gemini nema novog prepisa {age:.1f}s."
                else:
                    state = f"Zvuk je poslat; Gemini nema novog prepisa {age:.1f}s."
            elif self.last_response:
                state = f"Gemini je poslednji put odgovorio pre {now - self.last_response:.1f}s."
            else:
                state = "Čekam prvi odgovor Gemini-ja."
            return "\n".join([state, *list(self._recent)[-3:]])


def objasni(error: str) -> str:
    tekst = error.lower()
    if "još se zatvara" in tekst:
        return "Prethodno snimanje još oslobađa mikrofon; novi diktat nije pokrenut."
    if "mikrofon" in tekst:
        return "Mikrofon ne daje zvuk; proveri uređaj i dozvolu za mikrofon."
    if any(s in tekst for s in ("quota", "resource_exhausted", "rate limit", "429", "too many requests")):
        return "Ograničenje servisa ili kvote; proveri potrošnju i limite izabranog servisa."
    if any(s in tekst for s in ("api key", "ključ", "key not valid", "401", "403")):
        return "API ključ je odbijen; proveri ključ i pristup modelu."
    if any(s in tekst for s in ("timed out", "isteklo vreme", "prekinuta veza", "zatvorena", "slanje nije uspelo")):
        return "Veza sa servisom je prekinuta ili je isteklo čekanje; kvota nije potvrđena."
    if "nije vratio prepis" in tekst:
        return "Servis nije vratio konačan prepis; proveri vezu i pokušaj ponovo."
    return "Prepoznavanje nije uspelo; detalj je ispod."
