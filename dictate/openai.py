"""OpenAI audio transkripcija za desktop aplikaciju.

OpenAI dobija jedan zavrsen snimak tek kada korisnik zaustavi diktiranje.
Kljuc se cita iz lokalnog config.json fajla i nikad se ne upisuje u kod.
"""

import io
import json
import socket
import time
import urllib.error
import urllib.request
import uuid
import wave

from . import abbrev, flac, webstt


ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
MODEL = "gpt-transcribe"
USER_AGENT = "Diktat/1.0"
MAX_FILE_BYTES = 25 * 1024 * 1024
MIN_AUDIO_BYTES = 6400  # 0.2 s mono PCM-a na 16 kHz
RETRY_WAIT = 1.0
MAX_RETRIES = 5


class OpenAIError(Exception):
    """Грешка OpenAI позива; retryable означава да други покушај има смисла."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def enabled(cfg) -> bool:
    """Да ли је OpenAI изабран као извор транскрипције."""
    return cfg.get("transcription_provider", "google") == "openai"


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


def _prompt(script: str) -> str:
    instruction = {
        "cyrillic": "Пиши на српској ћирилици.",
        "latin": "Пиши на српској латиници.",
    }.get(script, "Користи писмо које најбоље одговара изговореном тексту.")
    return (
        "Тачно препиши српски диктат. Не преводи, не сажимај и не додај речи "
        "које нису изговорене. Сачувај бројеве и називе. " + instruction
    )


_CYRILLIC_TO_LATIN = str.maketrans({
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "Đ",
    "Е": "E", "Ж": "Ž", "З": "Z", "И": "I", "Ј": "J", "К": "K",
    "Л": "L", "Љ": "Lj", "М": "M", "Н": "N", "Њ": "Nj", "О": "O",
    "П": "P", "Р": "R", "С": "S", "Т": "T", "Ћ": "Ć", "У": "U",
    "Ф": "F", "Х": "H", "Ц": "C", "Ч": "Č", "Џ": "Dž", "Ш": "Š",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ",
    "е": "e", "ж": "ž", "з": "z", "и": "i", "ј": "j", "к": "k",
    "л": "l", "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "ć", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
})


def to_latin(text: str) -> str:
    """Преведи српску ћирилицу у латиницу без дирања осталог текста."""
    return text.translate(_CYRILLIC_TO_LATIN) if text else text


def post_process(text: str, cfg) -> str:
    """Примени само локална правила која не кваре интерпункцију модела."""
    text = (text or "").strip()
    if cfg.get("openai_output_script") == "latin":
        text = to_latin(text)
    text = webstt.join_thousands(text)
    if cfg.get("strip_punctuation", True):
        text = "\n".join(webstt.strip_punctuation(red) for red in text.split("\n"))
    if cfg.get("lowercase", True):
        text = text.lower()
    rules = abbrev.parse(
        cfg.get("abbreviation_rules") or abbrev.default_text()
    ) if cfg.get("abbreviations", True) else []
    # Brojevi napisani recima ostaju onako kako ih je transkripcija vratila;
    # lokalna pravila samo uredjuju jedinice i korisnicke skracenice.
    text = abbrev.apply(text, rules)
    if cfg.get("ascii_diacritics", False):
        text = webstt.to_ascii(text)
    return text


def recognize(pcm: bytes, cfg, timeout=180) -> str:
    """Пошаљи mono 16-bit PCM на OpenAI и врати транскрипт."""
    if not pcm:
        return ""
    key = (cfg.get("openai_api_key") or "").strip()
    if not key:
        raise OpenAIError("OpenAI API кључ није подешен.")
    if len(pcm) < MIN_AUDIO_BYTES:
        raise OpenAIError("Снимак је прекратак за OpenAI.")

    rate = int(cfg.get("sample_rate", 16000))
    if cfg.get("compress_audio", True):
        audio = flac.encode(pcm, rate)
    else:
        audio = None
    if audio:
        data, filename, content_type = audio, "diktat.flac", "audio/flac"
    else:
        data, filename, content_type = wav_bytes(pcm, rate), "diktat.wav", "audio/wav"
    if len(data) > MAX_FILE_BYTES:
        raise OpenAIError("Audio fajl je prevelik za OpenAI (najviše 25 MB).")

    fields = {
        "model": MODEL,
        "languages[]": (cfg.get("language", "sr-RS").split("-")[0] or "sr"),
        "prompt": _prompt(cfg.get("openai_output_script", "auto")),
        "response_format": "json",
        "temperature": "0",
    }
    body, content_type = _multipart(fields, "file", data, filename, content_type)
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": content_type,
            "User-Agent": USER_AGENT,
        },
    )
    print(f"[diktat] OpenAI transkripcija: {MODEL}, {len(data) / 1024:.0f} KB")
    for attempt in range(MAX_RETRIES + 1):
        try:
            payload = _request_json(request, timeout)
            text = str(payload.get("text") or "").strip()
            if not text:
                raise OpenAIError("OpenAI није вратио текст.", retryable=True)
            return text
        except OpenAIError as exc:
            if not exc.retryable or attempt == MAX_RETRIES:
                raise
            print(f"[diktat] {exc} — покушавам поново ({attempt + 1}/{MAX_RETRIES})")
            time.sleep(RETRY_WAIT * min(attempt + 1, 5))
            if attempt < MAX_RETRIES:
                continue
    raise OpenAIError("OpenAI није вратио текст.")


def _request_json(request, timeout: float):
    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:240]
        raise OpenAIError(
            _http_message(exc.code, detail),
            retryable=exc.code in (408, 429) or exc.code >= 500,
        ) from exc
    except urllib.error.URLError as exc:
        raise OpenAIError(
            f"Нема везе са OpenAI-јем ({exc.reason}).", retryable=True
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OpenAIError("OpenAI није одговорио на време.", retryable=True) from exc
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise OpenAIError("OpenAI је вратио неисправан одговор.") from exc
    if not isinstance(payload, dict):
        raise OpenAIError("OpenAI је вратио неочекиван одговор.")
    return payload


def _http_message(code: int, detail: str = "") -> str:
    if code in (401, 403):
        return f"OpenAI је одбио API кључ (HTTP {code})."
    if code == 400:
        return "OpenAI је одбио аудио или параметре (HTTP 400)." + (
            f" {detail}" if detail else ""
        )
    if code == 413:
        return "OpenAI је одбио превелик аудио фајл (HTTP 413)."
    if code == 429:
        return "OpenAI је ограничио број захтева (HTTP 429)."
    return f"OpenAI је вратио HTTP {code}." + (f" {detail}" if detail else "")
