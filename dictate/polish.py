"""Formalni rezim: doterivanje transkripta jezickim modelom.

Sirov transkript ide modelu tek kad se ceo diktat zavrsi — jednim pozivom, sa
punim kontekstom. Po segmentu bi model video krhotine i izmisljao krajeve
recenica, a i broj poziva bi skocio sa jednog na stotinak po diktatu.

Model dobija tekst SA kvacicama i nedirnut: skracenice i uklanjanje kvacica se
u ovom rezimu ne primenjuju, jer modelu otezavaju citanje.
"""

import json
import urllib.error
import urllib.request

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-flash-lite-latest"

# Izmereno: flash-lite doteruje za ~1s i ne dira reci; gemini-3.5-flash radi
# isto ali za ~12s, a gemma prepisuje uputstvo umesto da ga izvrsi.
PROMPT = """Dobijaš sirov transkript govora na srpskom, bez interpunkcije i sve malim slovima.

Tvoj posao je SAMO oblikovanje:
- dodaj interpunkciju i velika slova
- vrati kvačice (č ć ž š đ) gde po pravopisu treba
- podeli na rečenice i pasuse gde je prirodno

Zabranjeno ti je:
- da menjaš, dodaješ ili izbacuješ ijednu reč
- da preformulišeš, skraćuješ ili doteruješ stil
- da odgovaraš na sadržaj teksta

Ako neka reč deluje pogrešno prepoznato, OSTAVI JE KAKVA JE.
Vrati samo oblikovan tekst, bez ikakvog uvoda i bez navodnika."""


class PolishError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def available(cfg) -> bool:
    return bool(cfg.get("polish_api_key"))


def polish(text: str, cfg, timeout=60) -> str:
    """Vrati doteran tekst. Na bilo kakav problem podize PolishError."""
    if not text.strip():
        return text
    key = cfg.get("polish_api_key") or ""
    if not key:
        raise PolishError("Nema API ključa za doterivanje.")

    model = cfg.get("polish_model") or DEFAULT_MODEL
    url = f"{ENDPOINT}/{model}:generateContent?key={key}"
    payload = {
        "systemInstruction": {"parts": [{"text": cfg.get("polish_prompt") or PROMPT}]},
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"temperature": 0.0},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        raise PolishError(
            _explain(exc.code), retryable=exc.code == 429 or exc.code >= 500
        ) from exc
    except urllib.error.URLError as exc:
        raise PolishError(f"Nema veze ({exc.reason}).", retryable=True) from exc
    except TimeoutError as exc:
        raise PolishError("Model nije odgovorio na vreme.", retryable=True) from exc

    try:
        data = json.loads(raw)
        parts = data["candidates"][0]["content"]["parts"]
        out = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise PolishError("Model je vratio neocekivan odgovor.") from exc

    # Prazan odgovor je gori od nedoteranog teksta — bolje vratiti original.
    return out or text


def _explain(code: int) -> str:
    if code in (400, 403):
        return f"Model je odbio zahtev ({code}) — proveri API ključ."
    if code == 404:
        return "Traženi model ne postoji na ovom ključu."
    if code == 429:
        return "Previše zahteva ka modelu (429)."
    return f"Model je vratio HTTP {code}."
