"""Bezbedna provera pristupa API ključevima.

Provera samo čita listu dostupnih modela. Ne šalje audio ili tekst i ne ulazi u
transkripciju.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


# Groq je iza Cloudflare-a. Podrazumevani Python-urllib potpis dobija
# HTTP 403, error code 1010, pre nego sto kljuc uopste stigne do Groq-a.
USER_AGENT = "Diktat/1.0"
KEY_FIELDS = ("polish_api_key", "groq_api_key", "openai_api_key")


def apply_fields(cfg: dict, fields: dict) -> None:
    """Upisi kljuceve iz polja. Prazan unos ostaje prazan, razmaci se skidaju."""
    for key in KEY_FIELDS:
        if key in fields:
            cfg[key] = str(fields.get(key) or "").strip()


def _get(url: str, headers: dict[str, str] | None = None) -> dict:
    poslato = {"User-Agent": USER_AGENT}
    poslato.update(headers or {})
    request = urllib.request.Request(url, headers=poslato)
    try:
        raw = urllib.request.urlopen(request, timeout=30).read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:180]
        raise RuntimeError(f"HTTP {exc.code}" + (f": {detail}" if detail else "")) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"mrežna greška: {exc}") from exc
    try:
        result = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("neispravan odgovor") from exc
    if not isinstance(result, dict):
        raise RuntimeError("neočekivan odgovor")
    return result


def _one(name: str, key: str, url: str, headers: dict[str, str] | None, field: str) -> str:
    if not str(key or "").strip():
        return f"✗ {name}: ključ nije podešen"
    try:
        result = _get(url, headers)
        count = len(result.get(field) or [])
        return f"✓ {name}: ključ radi ({count} modela dostupno)"
    except Exception as exc:  # noqa: BLE001
        return f"✗ {name}: {exc}"


def check_all(cfg: dict) -> list[str]:
    gemini_key = str(cfg.get("polish_api_key") or "").strip()
    gemini_url = (
        "https://generativelanguage.googleapis.com/v1beta/models?key="
        + urllib.parse.quote(gemini_key, safe="")
    )
    return [
        _one("Gemini", gemini_key, gemini_url, None, "models"),
        _one(
            "Groq",
            cfg.get("groq_api_key"),
            "https://api.groq.com/openai/v1/models",
            {"Authorization": f"Bearer {cfg.get('groq_api_key', '')}"},
            "data",
        ),
        _one(
            "OpenAI",
            cfg.get("openai_api_key"),
            "https://api.openai.com/v1/models",
            {"Authorization": f"Bearer {cfg.get('openai_api_key', '')}"},
            "data",
        ),
    ]


def check_gemini(cfg: dict) -> str:
    """Check only the desktop transcription key, without audio or text."""
    key = str(cfg.get("polish_api_key") or "").strip()
    if not key:
        return "Gemini: API key is not set"
    url = "https://generativelanguage.googleapis.com/v1beta/models?key=" + urllib.parse.quote(key, safe="")
    try:
        _get(url)
        return "Gemini: API key works"
    except Exception as exc:
        # URLs in urllib errors can contain credentials.
        if isinstance(exc, RuntimeError) and str(exc).startswith("HTTP "):
            return "Gemini: " + str(exc).split(":", 1)[0]
        return "Gemini: connection failed"
