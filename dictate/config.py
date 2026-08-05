"""Konfiguracija — citanje/pisanje config.json u korenu projekta."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULTS = {
    # --- Prepoznavanje ---
    "language": "sr-RS",
    "api_key": "",                # prazno = ugradjeni javni Chromium kljuc
    "profanity_filter": False,    # True bi maskirao psovke ("sranje" -> "s*****")
    "capitalize_first": False,    # veliko pocetno slovo
    "lowercase": True,            # sve malim slovima

    # Na dugom diktatu seci na pauzi i slati delove dok korisnik jos prica.
    "auto_segment": False,
    "segment_after_seconds": 10,  # samo uz auto_segment
    "pause_seconds": 0.7,         # koliko tisine znaci "kraj misli"
    "max_request_seconds": 30,    # snimanje staje ovde; endpoint odbija duze
    "max_seconds": 290,           # gornja granica jednog pritiska tastera

    # --- Audio ---
    "sample_rate": 16000,
    "input_device": None,         # None = sistemski mikrofon, ili ime uredjaja
    "tail_seconds": 0.8,          # koliko jos snima posle pustanja tastera

    # --- Hotkey ---
    "hotkey": "cmd_r",            # cmd_l | alt_r | ctrl_r | f13 ...
    "mode": "hold",               # "hold" = drzi da snimas | "toggle"
    "min_seconds": 0.35,          # kraci pritisak se tretira kao obican Cmd

    # --- Izlaz ---
    "insert_method": "paste",     # "paste" | "type" | "clipboard_only"
    "restore_clipboard": True,
    "trailing_space": True,
    "history_size": 10,           # koliko poslednjih tekstova cuvati za kopiranje
    "show_overlay": False,        # pilula sa vremenom preko ekrana
    "overlay_position": "top-right",

    # --- Debug ---
    "debug": False,               # snimaj zvuk i tekst radi poredjenja
    "debug_dir": "~/Diktat-debug",
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Ne mogu da procitam {CONFIG_PATH}: {exc}") from exc
    return _migrate(cfg)


def _migrate(cfg: dict) -> dict:
    """Preuzmi vrednosti iz starih naziva i izbaci kljuceve kojih vise nema."""
    if "language_codes" in cfg:
        codes = cfg.pop("language_codes") or []
        if codes:
            cfg["language"] = codes[0]
    for staro, novo in (
        ("web_api_key", "api_key"),
        ("web_max_seconds", "max_request_seconds"),
    ):
        if staro in cfg:
            vrednost = cfg.pop(staro)
            if vrednost not in (None, ""):
                cfg[novo] = vrednost
    for mrtvo in ("engine", "credentials_json", "project_id",
                  "location", "model", "punctuation"):
        cfg.pop(mrtvo, None)
    return cfg


def save(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
