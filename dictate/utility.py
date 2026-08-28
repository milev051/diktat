"""Lokalna desetodnevna procena koristi diktiranja.

Podaci su namerno jednostavni i ostaju u lokalnom config.json-u: broj uspešnih
rezultata, karakteri, snimljene sekunde, korišćeni modeli i ručno upisan trošak.
"""

from __future__ import annotations

from datetime import date, timedelta


KEY = "utility_evaluation"
DAYS = 10
DEFAULT_TYPING_CPM = 180


def _today(value: date | None = None) -> date:
    return value or date.today()


def _blank(start: date) -> dict:
    return {
        "start_date": start.isoformat(),
        "spent": 0.0,
        "typing_cpm": DEFAULT_TYPING_CPM,
        "daily": {},
        "models": {},
    }


def start(cfg: dict, today: date | None = None) -> None:
    """Pokreni ili ponovo pokreni novu desetodnevnu procenu."""
    cfg[KEY] = _blank(_today(today))


def reset(cfg: dict) -> None:
    cfg.pop(KEY, None)


def _data(cfg: dict) -> dict | None:
    data = cfg.get(KEY)
    return data if isinstance(data, dict) and data.get("start_date") else None


def _period(data: dict) -> tuple[date, date] | None:
    try:
        start_date = date.fromisoformat(str(data["start_date"]))
    except (KeyError, TypeError, ValueError):
        return None
    return start_date, start_date + timedelta(days=DAYS - 1)


def _day(data: dict, when: date) -> dict | None:
    period = _period(data)
    if period is None or not (period[0] <= when <= period[1]):
        return None
    daily = data.setdefault("daily", {})
    row = daily.setdefault(
        when.isoformat(), {"dictations": 0, "characters": 0, "seconds": 0.0}
    )
    return row


def record_audio(cfg: dict, seconds: float, today: date | None = None) -> None:
    data = _data(cfg)
    row = _day(data, _today(today)) if data else None
    if row is not None and seconds > 0:
        row["seconds"] = float(row.get("seconds", 0.0)) + float(seconds)


def record_text(cfg: dict, text: str, today: date | None = None) -> None:
    clean = (text or "").strip()
    data = _data(cfg)
    row = _day(data, _today(today)) if data and clean else None
    if row is not None:
        row["dictations"] = int(row.get("dictations", 0)) + 1
        row["characters"] = int(row.get("characters", 0)) + len(clean)


def record_model(
    cfg: dict,
    provider: str,
    model: str,
    operation: str = "",
    seconds: float = 0.0,
    today: date | None = None,
) -> None:
    """Zabeleži uspešan poziv modelu u tekućoj proceni."""
    if not provider or not model:
        return
    data = _data(cfg)
    if data is None or _day(data, _today(today)) is None:
        return
    models = data.setdefault("models", {})
    key = "|".join((str(provider).strip(), str(model).strip(), str(operation).strip()))
    row = models.setdefault(
        key,
        {
            "provider": str(provider).strip(),
            "model": str(model).strip(),
            "operation": str(operation).strip(),
            "calls": 0,
            "seconds": 0.0,
        },
    )
    row["calls"] = int(row.get("calls", 0)) + 1
    row["seconds"] = float(row.get("seconds", 0.0)) + max(0.0, float(seconds))


def set_spent(cfg: dict, amount: float) -> None:
    data = _data(cfg)
    if data is not None:
        data["spent"] = max(0.0, float(amount))


def set_typing_cpm(cfg: dict, value: int) -> None:
    data = _data(cfg)
    if data is not None:
        data["typing_cpm"] = max(1, int(value))


def report(cfg: dict, today: date | None = None) -> dict:
    """Vrati zbir i dnevne redove za ekran procene."""
    data = _data(cfg)
    if data is None:
        return {"started": False}
    period = _period(data)
    if period is None:
        return {"started": False}

    now = _today(today)
    elapsed = min(DAYS, max(1, (now - period[0]).days + 1))
    last_day = min(now, period[1])
    days = []
    cursor = period[0]
    daily = data.get("daily", {})
    while cursor <= last_day:
        row = daily.get(cursor.isoformat(), {})
        days.append({
            "date": cursor.isoformat(),
            "dictations": int(row.get("dictations", 0)),
            "characters": int(row.get("characters", 0)),
            "seconds": float(row.get("seconds", 0.0)),
        })
        cursor += timedelta(days=1)

    total_dictations = sum(row["dictations"] for row in days)
    total_characters = sum(row["characters"] for row in days)
    total_seconds = sum(row["seconds"] for row in days)
    spent = max(0.0, float(data.get("spent", 0.0)))
    typing_cpm = max(1, int(data.get("typing_cpm", DEFAULT_TYPING_CPM)))
    typed_minutes = total_characters / typing_cpm
    return {
        "started": True,
        "start_date": period[0].isoformat(),
        "end_date": period[1].isoformat(),
        "elapsed_days": elapsed,
        "remaining_days": max(0, DAYS - elapsed),
        "spent": spent,
        "typing_cpm": typing_cpm,
        "days": days,
        "dictations": total_dictations,
        "characters": total_characters,
        "seconds": total_seconds,
        "typed_minutes": typed_minutes,
        "cost_per_dictation": spent / total_dictations if total_dictations else 0.0,
        "cost_per_1000_characters": (
            spent * 1000 / total_characters if total_characters else 0.0
        ),
        "models": sorted(
            (
                {
                    "provider": str(row.get("provider", "")),
                    "model": str(row.get("model", "")),
                    "operation": str(row.get("operation", "")),
                    "calls": int(row.get("calls", 0)),
                    "seconds": float(row.get("seconds", 0.0)),
                }
                for row in (data.get("models", {}) or {}).values()
                if isinstance(row, dict)
            ),
            key=lambda row: (row["provider"], row["model"], row["operation"]),
        ),
    }
