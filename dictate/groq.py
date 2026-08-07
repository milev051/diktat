"""Groq Whisper + GPT-OSS drugo misljenje za isti diktat.

Google Web Speech ostaje prvi prepis. Kada je ovaj alat ukljucen, audio svih
segmenata jednog diktata ide Whisper-u, a zatim GPT-OSS dobija oba prepisa i
vraca jednu proverenu verziju. API kljuc se cita samo iz lokalnog config-a.
"""

import base64
import io
import json
import time
import urllib.error
import urllib.request
import uuid
import wave


TRANSCRIPT_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
CHAT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_TRANSCRIPTION_MODEL = "whisper-large-v3"
DEFAULT_MERGE_MODEL = "openai/gpt-oss-120b"


class GroqError(Exception):
    """Greška Groq poziva; dodatna provera ne sme da obori diktat."""


def enabled(cfg) -> bool:
    return bool(cfg.get("groq_enabled", False)) and bool(cfg.get("groq_api_key"))


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def _multipart(fields: dict[str, str], name: str, data: bytes, filename: str,
              content_type: str) -> tuple[bytes, str]:
    boundary = "----diktat-" + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            str(value).encode(),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        data,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _request_json(request, timeout: float):
    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:240]
        raise GroqError(_http_message(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise GroqError(f"Nema veze sa Groq-om ({exc.reason}).") from exc
    except TimeoutError as exc:
        raise GroqError("Groq nije odgovorio na vreme.") from exc
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise GroqError("Groq je vratio neispravan odgovor.") from exc


def transcribe(delovi, cfg, timeout=90) -> str:
    """Prepiši spojene segmente jednim Whisper pozivom."""
    if not delovi:
        return ""
    key = (cfg.get("groq_api_key") or "").strip()
    if not key:
        raise GroqError("Nema Groq API ključa.")
    rate = int(delovi[0][1])
    pcm = b"".join(part for part, _ in delovi)
    body, content_type = _multipart(
        {
            "model": DEFAULT_TRANSCRIPTION_MODEL,
            "language": (cfg.get("language") or "sr-RS").split("-")[0],
            "temperature": "0",
            "response_format": "json",
        },
        "file",
        wav_bytes(pcm, rate),
        "diktat.wav",
        "audio/wav",
    )
    request = urllib.request.Request(
        TRANSCRIPT_ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": content_type},
    )
    payload = _request_json(request, timeout)
    text = (payload.get("text") or "").strip()
    if not text:
        raise GroqError("Whisper nije vratio prepis.")
    return text


def _merge_prompt(google_text: str, whisper_text: str, cfg) -> str:
    style = ""
    if cfg.get("text_style") == "written":
        style = (
            "\nPiši pravopisno pravilno: dodaj potrebne kvačice, velika slova i "
            "interpunkciju, bez menjanja značenja."
        )
    else:
        style = "\nZadrži govorni izgled: mala slova i bez interpunkcije."
    vocabulary = (cfg.get("vocabulary") or "").strip()
    terms = f"\nPoznati nazivi i skraćenice: {vocabulary}" if vocabulary else ""
    return f"""Ti si završni proveravač srpskog diktata.

Google prepis:
{google_text}

Groq Whisper prepis:
{whisper_text}

Uporedi oba prepisa i vrati jednu konačnu verziju. Ispravi reč samo kada se
iz zvuka i drugog prepisa vidi da je Google pogrešio ili nešto propustio.
Ako se ne slažu, biraj ono što ima uporište u drugom prepisu; ne izmišljaj,
ne dodaj objašnjenje, ne sažimaj, ne prevodi i ne odgovaraj na sadržaj.
Vrati samo konačan tekst, bez uvoda i navodnika.{style}{terms}"""


def merge(google_text: str, whisper_text: str, cfg, timeout=90) -> str:
    key = (cfg.get("groq_api_key") or "").strip()
    if not key:
        raise GroqError("Nema Groq API ključa.")
    prompt = _merge_prompt(google_text, whisper_text, cfg)
    payload = {
        "model": DEFAULT_MERGE_MODEL,
        "messages": [
            {"role": "system", "content": "Vraćaš samo konačan prepis diktata."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_completion_tokens": int(cfg.get("groq_max_completion_tokens", 2048)),
        "top_p": 1,
        "reasoning_effort": cfg.get("groq_reasoning_effort", "medium"),
        "stream": False,
    }
    request = urllib.request.Request(
        CHAT_ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    response = _request_json(request, timeout)
    try:
        content = response["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        text = str(content or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise GroqError("Groq GPT-OSS nije vratio tekst.") from exc
    if not text:
        raise GroqError("Groq GPT-OSS je vratio prazan tekst.")
    return text


def check_batch(delovi, google_text: str, cfg, timeout=180) -> str:
    """Whisper + poređenje sa Google prepisom u dva poziva."""
    whisper_text = transcribe(delovi, cfg, timeout=min(timeout, 120))
    return merge(google_text, whisper_text, cfg, timeout=timeout)


def _http_message(code: int, detail: str = "") -> str:
    if code in (401, 403):
        return "Groq je odbio API ključ (HTTP %d)." % code
    if code == 404:
        return "Groq model ili endpoint ne postoji (HTTP 404)."
    if code == 429:
        return "Groq je ograničio broj zahteva (HTTP 429)."
    return f"Groq je vratio HTTP {code}." + (f" {detail}" if detail else "")
