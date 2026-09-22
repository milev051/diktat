"""Groq GPT-OSS kao model za AI obradu vec prepoznatog teksta.

Ovde se ne salje zvuk. Drugo misljenje o snimku (Whisper pa spajanje sa
Google prepisom) je uklonjeno 22.09.2026; kako je radilo i zasto je
uklonjeno stoji u docs/provera-snimka.md. API kljuc se cita samo iz lokalnog
config-a.
"""

import json
import urllib.error
import urllib.request


CHAT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_TEXT_MODEL = "openai/gpt-oss-120b"
USER_AGENT = "Diktat/1.0"


class GroqError(Exception):
    """Greška Groq poziva; obrada teksta ne sme da obori diktat."""


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


def manipulate_text(text: str, cfg, instruction: str, timeout=60) -> str:
    """Obradi već prepoznat tekst bez slanja audio-snimka."""
    key = (cfg.get("groq_api_key") or "").strip()
    if not key:
        raise GroqError("Nema Groq API ključa za obradu teksta.")
    payload = {
        "model": DEFAULT_TEXT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Obrađuješ diktirani tekst. Poštuj uputstvo doslovno i "
                    "vrati samo konačan tekst."
                ),
            },
            {
                "role": "user",
                "content": f"{instruction}\n\nSirov transkript:\n{text}",
            },
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
            "User-Agent": USER_AGENT,
        },
    )
    response = _request_json(request, timeout)
    try:
        content = response["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        result = str(content or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise GroqError("Groq GPT-OSS nije vratio tekst za obradu.") from exc
    if not result:
        raise GroqError("Groq GPT-OSS je vratio prazan tekst za obradu.")
    return result


def _http_message(code: int, detail: str = "") -> str:
    if code in (401, 403):
        return "Groq je odbio API ključ (HTTP %d)." % code
    if code == 404:
        return "Groq model ili endpoint ne postoji (HTTP 404)."
    if code == 429:
        return "Groq je ograničio broj zahteva (HTTP 429)."
    return f"Groq je vratio HTTP {code}." + (f" {detail}" if detail else "")
