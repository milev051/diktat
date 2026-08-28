"""Bezbedna provera pristupa API ključevima.

Provera samo čita listu dostupnih modela. Ne šalje audio ili tekst i ne ulazi u
transkripciju.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


def _get(url: str, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
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
