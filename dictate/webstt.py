"""Besplatni Google Web Speech endpoint — onaj koji koristi Chromium.

Bez naloga i bez kredencijala. Isti onaj koji `SpeechRecognition.recognize_google()`
zove vec godinama. Srpski radi vrlo dobro.

Ogranicenja, znaj ih:
  * BATCH, ne streaming — tekst stize tek kad se posalje ceo komad
    (~1.2s za snimke do 30s).
  * Nema automatske interpunkcije ni velikih slova.
  * Endpoint je nedokumentovan i kljuc je javni Chromium kljuc. Radi godinama,
    ali Google ga moze ugasiti bez najave.
  * Prakticno ide do ~30s po zahtevu; duze snimke bolje seci.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import flac

ENDPOINT = "https://www.google.com/speech-api/v2/recognize"
DEFAULT_KEY = "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"


class WebSttError(Exception):
    """`retryable` je True samo za prolazne smetnje — mrezu, 429 i 5xx.

    Odbijen kljuc (403) ili neispravan zahtev (400) se ne ponavljaju: drugi
    pokusaj bi dao isto, a diktat bi samo duze cekao.
    """

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


RETRY_WAIT = 1.0


def recognize(
    pcm: bytes,
    language="sr-RS",
    sample_rate=16000,
    key=None,
    timeout=30,
    profanity_filter=False,
    retries=1,
):
    """Salje sirov 16-bit PCM i vraca prepoznat tekst ('' ako nista).

    Bez `pFilter=0` Google maskira psovke zvezdicama ("sranje" -> "s*****").
    Ime parametra je osetljivo na velika slova — `pfilter` se ignorise.
    """
    return recognize_full(
        pcm, language, sample_rate, key, timeout, profanity_filter, retries
    )[0]


def recognize_full(
    pcm: bytes,
    language="sr-RS",
    sample_rate=16000,
    key=None,
    timeout=30,
    profanity_filter=False,
    retries=1,
    compress=True,
):
    """Kao `recognize`, ali vraca i pouzdanost — (tekst, 0.0-1.0).

    Pouzdanost je jedini signal koji endpoint daje o tome koliko je siguran u
    ono sto je cuo; po njoj se odlucuje da li vredi drugo misljenje.
    """
    if not pcm:
        return "", 0.0

    for attempt in range(retries + 1):
        try:
            return _request(
                pcm, language, sample_rate, key, timeout, profanity_filter, compress
            )
        except WebSttError as exc:
            if attempt >= retries or not exc.retryable:
                raise
            print(f"[diktat] {exc} — pokusavam ponovo")
            time.sleep(RETRY_WAIT)
    return "", 0.0


def _request(pcm, language, sample_rate, key, timeout, profanity_filter,
             compress=True):
    # FLAC je 36-42% manji, a prepis isti. Ako ffmpeg ne postoji ili zakaze,
    # salje se sirov PCM — usteda ne sme da obori diktat.
    telo, tip = pcm, f"audio/l16; rate={sample_rate}"
    if compress:
        sazeto = flac.encode(pcm, sample_rate)
        if sazeto:
            # Bez `rate=` i sa `audio/flac` endpoint vraca 400 — iskljucivo ovako.
            telo, tip = sazeto, f"audio/x-flac; rate={sample_rate}"
    url = (
        f"{ENDPOINT}?client=chromium"
        f"&lang={urllib.parse.quote(language)}"
        f"&key={key or DEFAULT_KEY}"
        f"&pFilter={1 if profanity_filter else 0}"
    )
    request = urllib.request.Request(url, data=telo, headers={"Content-Type": tip})

    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        raise WebSttError(
            _explain_http(exc.code),
            retryable=exc.code == 429 or exc.code >= 500,
        ) from exc
    except urllib.error.URLError as exc:
        raise WebSttError(
            f"Nema veze sa internetom ({exc.reason}).", retryable=True
        ) from exc
    except TimeoutError as exc:
        raise WebSttError("Isteklo vreme cekanja.", retryable=True) from exc

    return _parse(raw.decode("utf-8", "replace"))


def _parse(body: str):
    """Odgovor je vise JSON linija; prva je obicno prazna {"result":[]}."""
    best = ""
    best_conf = -1.0
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        for result in payload.get("result", []):
            for alt in result.get("alternative", []):
                text = (alt.get("transcript") or "").strip()
                conf = float(alt.get("confidence", 0.0))
                if text and conf >= best_conf:
                    best, best_conf = text, conf
    return best, max(best_conf, 0.0)


def _explain_http(code: int) -> str:
    if code == 403:
        return "Google je odbio kljuc (403) — endpoint je verovatno stegnut."
    if code == 400:
        return "Neispravan zahtev (400) — proveri jezik i sample_rate."
    if code == 429:
        return "Previse zahteva (429). Sacekaj malo."
    return f"Google je vratio HTTP {code}."


# Tacka, zarez i dvotacka se brisu samo kad NISU izmedju cifara: endpoint ih
# vraca kao decimalni separator ("3,5") i kao satnicu ("10:00"), pa bi ih slepo
# brisanje spojilo u 35 i 1000. Crtica se brise samo kad stoji sama, da
# "crno-beli" ostane celo.
_PUNCT = re.compile(
    r"(?<!\d)[.,:]"     # tacka/zarez/dvotacka bez cifre ispred
    r"|[.,:](?!\d)"     # ili bez cifre iza
    r"|[!?;…«»„“”\"()\[\]{}]"
    r"|(?<=\s)[-–—](?=\s)"
)


# Tacka je separator hiljada samo ako je prate TACNO tri cifre i tu se broj
# zavrsava: "5.000" -> "5000", ali "verzija 2.0" i "android 4.4" ostaju celi.
_THOUSANDS = re.compile(r"(?<=\d)\.(?=\d{3}(?!\d))")


def join_thousands(text: str) -> str:
    prethodno = None
    while text != prethodno:        # "1.500.000" ima vise tacaka
        prethodno = text
        text = _THOUSANDS.sub("", text)
    return text


def strip_punctuation(text: str) -> str:
    """Skloni interpunkciju, ali ne diraj brojeve ni spojene reci."""
    if not text:
        return text
    return " ".join(_PUNCT.sub("", text).split())


_DIACRITICS = str.maketrans({
    "č": "c", "ć": "c", "ž": "z", "š": "s", "đ": "dj",
    "Č": "C", "Ć": "C", "Ž": "Z", "Š": "S", "Đ": "Dj",
})


def to_ascii(text: str) -> str:
    """č ć ž š đ -> c c z s dj. Opciono; podrazumevano iskljuceno."""
    return text.translate(_DIACRITICS) if text else text


def tidy(text: str) -> str:
    """Endpoint ne vraca veliko pocetno slovo — bar to doteramo."""
    if not text:
        return text
    return text[0].upper() + text[1:]
