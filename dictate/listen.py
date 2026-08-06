"""Drugo misljenje o snimku: model slusa zvuk i ispravlja prvi prepis.

Zasto uz prvi prepis a ne sam: izmereno na tri recenice, cisto i sa sumom
(SNR 5 dB), greska po reci —

    Web Speech         cist 0.21 | sum 0.30
    model sam          cist 0.12 | sum 0.29
    model + prepis     cist 0.17 | sum 0.17

Model sam je u sumu **halucinirao** ("poslao sam ponovo 250.000 dinara u 1:33"
umesto "...ponudu... u utorak u deset i trideset"): kad ne cuje, dopuni umesto
da ostavi rupu. Prvi prepis mu sluzi kao sidro, pa nema sta da izmislja.

Salje se WAV, ne sirov PCM: `inline_data` trazi poznat format, a WAV zaglavlje
je 44 bajta. Zvuk ide u base64, sto ga uveca za trecinu — zato ovo i postoji
kao odvojena opcija, a ne kao stalno ponasanje.
"""

import base64
import io
import json
import urllib.error
import urllib.request
import wave

from .polish import DEFAULT_MODEL, ENDPOINT, PolishError, _explain

# Ispod ovoga se prepis smatra nesigurnim. Izmereno: dobar srpski diktat vraca
# 0.92-0.95, ALI i pogresan ume da vrati 0.93 ("...postavio sastanak... iz kragu",
# odsecena rec, pouzdanost 0.93). Filter zato stedi podatke, a ne hvata greske —
# otud podrazumevano iskljucen.
PRAG = 0.85

# Skracenice i strani nazivi su najslabija tacka: endpoint ih mapira na obicnu
# rec ("AI" -> "pa", "i"), a model bez spiska nema po cemu da ih prepozna.
POJMOVI_PODRAZUMEVANO = "AI, API, Gemini, Android, iOS, macOS, Google, GitHub, endpoint, FLAC, APK"

UPUTSTVO = """Slušaš snimak govora na srpskom i vraćaš tačan prepis.

Drugi prepoznavač je čuo ovo: „{prepis}"

Uporedi sa snimkom i ispravi mesta gde je pogrešio. Ako se snimak i taj prepis
slažu, vrati ga nepromenjenog.

Granice:
- ne dodaj reči kojih na snimku nema — ako nešto ne razaznaješ, ostavi kako je
  prepoznavač čuo
- ne prevodi, ne skraćuj i ne doteruj stil
- ne odgovaraj na sadržaj, ovo je diktat

Vrati samo prepis, bez uvoda i bez navodnika."""

POJMOVI_DEO = """

Ovi pojmovi se često javljaju u ovim diktatima; ako čuješ nešto slično, napiši
ih tačno ovako: {pojmovi}"""


def enabled(cfg) -> bool:
    return bool(cfg.get("audio_check", False)) and bool(cfg.get("polish_api_key"))


def should_check(cfg, confidence: float) -> bool:
    """Vredi li slati snimak modelu."""
    if not enabled(cfg):
        return False
    if not cfg.get("audio_check_low_only", False):
        return True
    return confidence < float(cfg.get("audio_check_threshold", PRAG))


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _uputstvo(prepis: str, cfg) -> str:
    tekst = UPUTSTVO.format(prepis=prepis)
    pojmovi = cfg.get("vocabulary", POJMOVI_PODRAZUMEVANO)
    if pojmovi and pojmovi.strip():
        tekst += POJMOVI_DEO.format(pojmovi=pojmovi.strip())
    return tekst


def check(pcm: bytes, sample_rate: int, prepis: str, cfg, timeout=90) -> str:
    """Vrati ispravljen prepis. Na bilo kakav problem podize PolishError."""
    key = cfg.get("polish_api_key") or ""
    if not key or not pcm:
        raise PolishError("Nema API ključa za proveru snimka.")

    model = cfg.get("polish_model") or DEFAULT_MODEL
    payload = {
        "contents": [{
            "parts": [
                {"text": _uputstvo(prepis, cfg)},
                {"inline_data": {
                    "mime_type": "audio/wav",
                    "data": base64.b64encode(wav_bytes(pcm, sample_rate)).decode(),
                }},
            ]
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
