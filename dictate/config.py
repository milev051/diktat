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
    # Podrazumevano je "spoken": mala slova, bez interpunkcije. "written" znaci
    # da model sredjuje tekst — prekidac za to stoji u AI grupi.
    "text_style": "spoken",
    "ascii_diacritics": False,    # č ć ž š đ -> c c z s dj; nezavisno od stila
    "abbreviations": True,        # „ne znam" -> „nzm"
    "abbreviation_rules": "",     # prazno = ugradjena lista (dictate/abbrev.py)

    # Na dugom diktatu seci na pauzi i slati delove dok korisnik jos prica.
    "segment_after_seconds": 0,   # 0 = seci na svakoj pauzi, ma koliko kratak segment
    "pause_seconds": 0.7,         # koliko tisine znaci "kraj misli"
    "max_request_seconds": 30,    # snimanje staje ovde; endpoint odbija duze

    # --- Audio ---
    "sample_rate": 16000,
    "input_device": None,         # None = sistemski mikrofon, ili ime uredjaja
    "tail_seconds": 0.8,          # koliko jos snima posle pustanja tastera

    # --- Hotkey ---
    "hotkey": "alt_r",            # desni Option; cmd_r | ctrl_r | f13 ...
    "mode": "toggle",             # nacin aktivacije: "hold" | "toggle"
    "continuous": True,           # bez granice; sece na svakoj pauzi
    "continuous_max_seconds": 3600,  # sigurnosna granica i za neprekidni
    "min_seconds": 0.35,          # kraci pritisak se tretira kao obican Cmd

    # --- Izlaz ---
    "insert_method": "paste",     # "paste" | "type" | "clipboard_only"
    "restore_clipboard": True,
    "history_size": 10,           # koliko poslednjih tekstova cuvati za kopiranje
    "show_overlay": False,        # pilula sa vremenom preko ekrana
    "overlay_position": "top-right",

    # --- Formalni rezim (doterivanje jezickim modelom) ---
    "polish": False,              # ukljucuje se iz menija, samo uz kljuc
    "polish_api_key": "",         # Google AI Studio kljuc; ostaje pri nadogradnji
    "polish_model": "",           # prazno = gemini-flash-lite-latest
    "polish_prompt": "",          # prazno = ugradjeno uputstvo
    "polish_paragraphs": True,    # podeli na pasuse, prazan red izmedju
    "audio_check": False,         # model slusa snimak i ispravlja prepis
    "compress_audio": True,       # FLAC preko ffmpeg-a ako ga ima; inace PCM/WAV
    "audio_check_max_seconds": 120,  # koliko zvuka najvise cuvamo za grupnu proveru
    # Skracenice i nazivi koje endpoint stalno gresi; idu modelu uz snimak.
    "vocabulary": "AI, API, Gemini, Android, iOS, macOS, Google, GitHub, endpoint, FLAC, APK",
    # Slobodan opis: "makedonski", "pola makedonski pola srpski", "engleski
    # formalno"… Prazno = bez prevoda.
    "output_language": "",      # skrati i pojednostavi, bez gubitka sadrzaja

    # --- Debug ---
    "debug": False,               # snimaj zvuk i tekst radi poredjenja
    "debug_dir": "~/Diktat-debug",
    "pending_dir": "~/Diktat-neuspeli",  # snimci koje prepoznavanje nije primilo
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
    # Tri prekidaca za izgled teksta postala su jedan izbor. Zatecena
    # podesavanja se prevode, da niko ne izgubi ono sto je vec namestio.
    if "text_style" not in cfg:
        if cfg.get("polish") and cfg.get("polish_tidy", True):
            cfg["text_style"] = "written"
        else:
            cfg["text_style"] = "spoken"
    # "raw" je uklonjen: niko ga nije koristio, a bio je treci ishod za isto pitanje.
    if cfg.get("text_style") == "raw":
        cfg["text_style"] = "spoken"

    for mrtvo in ("engine", "credentials_json", "project_id", "location",
                  "model", "punctuation", "lowercase", "strip_punctuation",
                  "polish_tidy", "auto_segment", "max_seconds",
                  "audio_check_low_only", "audio_check_threshold",
                  "polish_emoji", "polish_emoji_rate", "polish_emoji_recent",
                  "join_thousands", "trailing_space", "capitalize_first",
                  "polish_level", "polish_concise"):
        cfg.pop(mrtvo, None)
    return cfg


def style(cfg) -> str:
    """spoken | written — jedini izvor istine o izgledu teksta."""
    return "written" if cfg.get("text_style") == "written" else "spoken"


def save(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
