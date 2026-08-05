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
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://www.google.com/speech-api/v2/recognize"
DEFAULT_KEY = "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"


class WebSttError(Exception):
    pass


def recognize(
    pcm: bytes,
    language="sr-RS",
    sample_rate=16000,
    key=None,
    timeout=30,
    profanity_filter=False,
):
    """Salje sirov 16-bit PCM i vraca prepoznat tekst ('' ako nista).

    Bez `pFilter=0` Google maskira psovke zvezdicama ("sranje" -> "s*****").
    Ime parametra je osetljivo na velika slova — `pfilter` se ignorise.
    """
    if not pcm:
        return ""

    url = (
        f"{ENDPOINT}?client=chromium"
        f"&lang={urllib.parse.quote(language)}"
        f"&key={key or DEFAULT_KEY}"
        f"&pFilter={1 if profanity_filter else 0}"
    )
    request = urllib.request.Request(
        url,
        data=pcm,
        headers={"Content-Type": f"audio/l16; rate={sample_rate}"},
    )

    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        raise WebSttError(_explain_http(exc.code)) from exc
    except urllib.error.URLError as exc:
        raise WebSttError(f"Nema veze sa internetom ({exc.reason}).") from exc

    return _parse(raw.decode("utf-8", "replace"))


def _parse(body: str) -> str:
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
    return best


def _explain_http(code: int) -> str:
    if code == 403:
        return "Google je odbio kljuc (403) — endpoint je verovatno stegnut."
    if code == 400:
        return "Neispravan zahtev (400) — proveri jezik i sample_rate."
    if code == 429:
        return "Previse zahteva (429). Sacekaj malo."
    return f"Google je vratio HTTP {code}."


# Tacka i zarez se brisu samo kad NISU izmedju cifara: endpoint ih vraca kao
# decimalni separator ("3,5", "20,5 RSD"), pa bi ih slepo brisanje spojilo u 35.
# Crtica se brise samo kad stoji sama, da "crno-beli" ostane celo.
_PUNCT = re.compile(
    r"(?<!\d)[.,]"      # tacka/zarez bez cifre ispred
    r"|[.,](?!\d)"      # ili bez cifre iza
    r"|[!?;:…«»„“”\"()\[\]{}]"
    r"|(?<=\s)[-–—](?=\s)"
)


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
