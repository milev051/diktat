"""Sitne zajednicke funkcije za delove aplikacije."""


def _label(text: str, limit=52) -> str:
    jedan_red = " ".join(text.split())
    return jedan_red if len(jedan_red) <= limit else jedan_red[: limit - 1] + "…"


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return text[0][:200] if text else exc.__class__.__name__
