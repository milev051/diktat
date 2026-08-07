"""Drugo misljenje o snimku: model slusa zvuk i ispravlja prvi prepis.

Zasto uz prvi prepis a ne sam: izmereno na tri recenice, cisto i sa sumom
(SNR 5 dB), greska po reci —

    Web Speech         cist 0.21 | sum 0.30
    model sam          cist 0.12 | sum 0.29
    model + prepis     cist 0.17 | sum 0.17

Model sam je u sumu **halucinirao** ("poslao sam ponovo 250.000 dinara u 1:33"
umesto "...ponudu... u utorak u deset i trideset"): kad ne cuje, dopuni umesto
da ostavi rupu. Prvi prepis mu sluzi kao sidro, pa nema sta da izmislja.

`inline_data` trazi poznat format — sirov PCM ne prolazi. Salje se FLAC ako
ffmpeg postoji, inace WAV. Zvuk ide u base64, sto ga uveca za trecinu, pa ovo i
postoji kao odvojena opcija a ne kao stalno ponasanje.

Ceo diktat ide JEDNIM pozivom, sa svim segmentima kao odvojenim delovima:
provera po segmentu je trosila 6-9 poziva na jednu diktiranu poruku, a model je
uz to video samo krhotinu umesto celine.
"""

import base64
import io
import json
import urllib.error
import urllib.request
import wave

from . import flac
from .polish import DEFAULT_MODEL, ENDPOINT, PolishError, _explain

# Ispod ovoga se prepis smatra nesigurnim. Izmereno: dobar srpski diktat vraca
# 0.92-0.95, ALI i pogresan ume da vrati 0.93 ("...postavio sastanak... iz kragu",
# odsecena rec, pouzdanost 0.93). Filter zato stedi podatke, a ne hvata greske —
# otud podrazumevano iskljucen.
PRAG = 0.85

# Skracenice i strani nazivi su najslabija tacka: endpoint ih mapira na obicnu
# rec ("AI" -> "pa", "i"), a model bez spiska nema po cemu da ih prepozna.
POJMOVI_PODRAZUMEVANO = "AI, API, Gemini, Android, iOS, macOS, Google, GitHub, endpoint, FLAC, APK"

UPUTSTVO = """Slušaš {sta} govora na srpskom i vraćaš tačan prepis.

Drugi prepoznavač je čuo ovo: „{prepis}"

Uporedi sa snimkom i ispravi mesta gde je pogrešio. Ako se snimak i taj prepis
slažu, vrati ga nepromenjenog.

Granice:
- ne dodaj reči kojih na snimku nema — ako nešto ne razaznaješ, ostavi kako je
  prepoznavač čuo
- engleske reči i nazive piši izvorno, kako se pišu u engleskom (deploy, build,
  push, branch, screenshot), a ne onako kako zvuče — ali ne izmišljaj oblike
  kojih nema
- ne prevodi, ne skraćuj i ne doteruj stil
- ne odgovaraj na sadržaj, ovo je diktat

Vrati samo prepis, bez uvoda i bez navodnika."""

VISE_DELOVA = """

Snimci su uzastopni delovi jednog istog diktata, datim redom. Vrati ceo tekst
spojen u jednu celinu, bez oznaka delova i bez praznih redova između njih."""

# Kad je "sredi tekst" ukljuceno, oblikovanje radi OVAJ prolaz — drugi poziv se
# tada preskace. Bez ovoga bi model oblikovao uzgred, pa nekad i ne bi.
SREDI_DEO = """

Piši pravilno: interpunkcija, velika slova i kvačice (č ć ž š đ) gde po
pravopisu treba. Ne menjaj reči zbog toga — samo ih ispiši kako se pišu."""

POJMOVI_DEO = """

Ovi pojmovi se često javljaju u ovim diktatima; ako čuješ nešto slično, napiši
ih tačno ovako: {pojmovi}"""


def enabled(cfg) -> bool:
    return bool(cfg.get("audio_check", False)) and bool(cfg.get("polish_api_key"))


def should_check(cfg, confidence: float = 0.0) -> bool:
    """Vredi li slati snimak modelu.

    Pouzdanost se vise ne gleda: izmereno je da endpoint prijavi 0.93 i za
    prepis sa odsecenom recju, pa je filtriranje po njoj stedelo podatke a
    propustalo greske. Prekidac za to je uklonjen.
    """
    return enabled(cfg)


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _uputstvo(prepis: str, cfg, delova: int = 1) -> str:
    tekst = UPUTSTVO.format(
        prepis=prepis, sta="snimak" if delova == 1 else f"{delova} uzastopna snimka"
    )
    if delova > 1:
        tekst += VISE_DELOVA
    from . import config
    if config.style(cfg) == "written":
        tekst += SREDI_DEO
    pojmovi = cfg.get("vocabulary", POJMOVI_PODRAZUMEVANO)
    if pojmovi and pojmovi.strip():
        tekst += POJMOVI_DEO.format(pojmovi=pojmovi.strip())
    return tekst


def _deo(pcm: bytes, sample_rate: int, compress=True) -> dict:
    """Jedan snimak kao `inline_data`, sazet koliko god moze.

    Redosled je namerno AAC pa FLAC pa WAV: izmereno na istom snimku 18 / 85 /
    139 KB uz identican prepis. Model gubitno sazimanje ne primeti, a zvuk se
    salje u base64 pa svaki usteden bajt vredi.
    """
    zvuk, tip = None, "audio/wav"
    if compress:
        zvuk = flac.encode_aac(pcm, sample_rate)
        if zvuk:
            tip = "audio/aac"
        else:
            zvuk = flac.encode(pcm, sample_rate)
            if zvuk:
                tip = "audio/flac"
    return {"inline_data": {
        "mime_type": tip,
        "data": base64.b64encode(zvuk or wav_bytes(pcm, sample_rate)).decode(),
    }}


def check(pcm: bytes, sample_rate: int, prepis: str, cfg, timeout=90) -> str:
    """Jedan snimak. Zadrzano zbog ponovnog slanja neuspelih diktata."""
    return check_batch([(pcm, sample_rate)], prepis, cfg, timeout)


def check_batch(delovi, prepis: str, cfg, timeout=180) -> str:
    """Vrati ispravljen prepis celog diktata. Na problem podize PolishError."""
    key = cfg.get("polish_api_key") or ""
    if not key or not delovi:
        raise PolishError("Nema API ključa za proveru snimka.")

    model = cfg.get("polish_model") or DEFAULT_MODEL
    compress = bool(cfg.get("compress_audio", True))
    payload = {
        "contents": [{
            "parts": [{"text": _uputstvo(prepis, cfg, len(delovi))}]
            + [_deo(pcm, rate, compress) for pcm, rate in delovi],
        }],
        "generationConfig": {"temperature": 0.0},
    }
    request = urllib.request.Request(
        f"{ENDPOINT}/{model}:generateContent?key={key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        raise PolishError(_explain(exc.code), retryable=exc.code >= 500) from exc
    except urllib.error.URLError as exc:
        raise PolishError(f"Nema veze ({exc.reason}).", retryable=True) from exc
    except TimeoutError as exc:
        raise PolishError("Model nije odgovorio na vreme.", retryable=True) from exc

    try:
        kandidat = json.loads(raw)["candidates"][0]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise PolishError("Model je vratio neocekivan odgovor.") from exc

    parts = kandidat.get("content", {}).get("parts")
    if not parts:
        razlog = kandidat.get("finishReason", "nepoznato")
        raise PolishError(f"Model nije vratio prepis ({razlog}).")

    out = "".join(p.get("text", "") for p in parts).strip()
    # Prazan odgovor znaci da nista nije razaznao — nas prepis je bolji od niceg.
    return out or prepis
