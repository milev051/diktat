"""Konfiguracija — citanje/pisanje config.json u korenu projekta."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

# Ugrađeni ključevi su podrazumevani samo da nova instalacija odmah radi.
# Lokalni config.json i dalje može da ih zameni drugim ključem.
DEFAULT_POLISH_API_KEY = ""
DEFAULT_GROQ_API_KEY = ""

# Izvori transkripcije; nepoznata vrednost bezbedno pada na Google, da
# postojece instalacije nastave da rade.
PROVIDERS = ("google", "openai", "gemini_live")

DEFAULTS = {
    # --- Prepoznavanje ---
    # "google" = besplatni Web Speech endpoint; "openai" = GPT transkripcija;
    # "gemini_live" = gemini-3.5-transcribe-live preko Live API-ja.
    # Obicni "gemini" (gemini-3.5-transcribe) je uklonjen: 25 zahteva dnevno
    # na besplatnom nivou ne znaci nista za svakodnevni rad.
    "transcription_provider": "google",
    "language": "sr-RS",
    "api_key": "",                # prazno = ugradjeni javni Chromium kljuc
    "openai_api_key": "",          # opciono; koristi se samo uz OpenAI provajder
    "openai_output_script": "latin",  # OpenAI desktop output is always Latin
    "openai_long_recording": True, # OpenAI dugi diktat, uz sigurnosni limit
    "openai_max_seconds": 3600,    # najviše 60 minuta po jednom OpenAI diktatu
    "recorded_seconds": 0.0,       # ukupno vreme uhvaćenog zvuka na ovom računaru
    # Maskiranje psovki je uklonjeno kao podesavanje: uvek `pFilter=0`.
    # Podrazumevano je "spoken": mala slova, bez interpunkcije. "written" znaci
    # da model sredjuje tekst — prekidac za to stoji u AI grupi.
    "text_style": "spoken",
    "lowercase": True,             # независно од интерпункције
    "strip_punctuation": True,     # бројеви типа 10:30 и 3,5 остају читави
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
    # "auto" kuca tekst i clipboard uopste ne dira; prelazi na lepljenje samo
    # kad tekst ima nov red, jer bi ga kucanje poslalo kao Enter.
    "insert_method": "auto",      # "auto" | "type" | "paste" | "clipboard_only"
    "restore_clipboard": True,
    "history_size": 5,            # koliko poslednjih tekstova cuvati za kopiranje
    "show_overlay": False,        # pilula sa vremenom preko ekrana
    "overlay_position": "top-right",

    # --- Formalni rezim (doterivanje jezickim modelom) ---
    "polish_api_key": DEFAULT_POLISH_API_KEY,  # Google AI Studio kljuc
    "polish_model": "",           # prazno = gemini-flash-lite-latest
    "text_model": "gemini",       # "gemini" | "groq"
    "polish_prompt": "",          # prazno = ugradjeno uputstvo
    "polish_paragraphs": True,
    # Preuredi u spisak tacaka (nalik ASD-STE100); iskljucuje pasuse.
    "polish_bullets": False,
    # Izbaci slucajno udvojene reci i fraze (govorna ispravka).
    "polish_dedupe": False,    # podeli na pasuse, prazan red izmedju
    "audio_check": False,         # model slusa snimak i ispravlja prepis
    "compress_audio": True,       # FLAC preko ffmpeg-a ako ga ima; inace PCM/WAV
    "audio_check_max_seconds": 120,  # koliko zvuka najvise cuvamo za grupnu proveru
    # --- Groq (Whisper + GPT-OSS drugo misljenje) ---
    "groq_enabled": False,
    "groq_api_key": DEFAULT_GROQ_API_KEY,
    "groq_reasoning_effort": "medium",
    "groq_max_completion_tokens": 2048,
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
    saved = {}
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update(saved)
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Ne mogu da procitam {CONFIG_PATH}: {exc}") from exc
    return _migrate(cfg, saved)


def _migrate(cfg: dict, saved=None) -> dict:
    """Preuzmi vrednosti iz starih naziva i izbaci kljuceve kojih vise nema."""
    saved = cfg if saved is None else saved
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
    # Zatecen "paste" je bio stari podrazumevani, ne izbor korisnika: prelazi se
    # na "auto", da clipboard ostane cist. Ko bas hoce lepljenje, upise "paste"
    # posle ove izmene i vise se ne dira.
    if cfg.get("insert_method") == "paste" and not cfg.get("_insert_migrated"):
        cfg["insert_method"] = "auto"
        cfg["_insert_migrated"] = True

    # Izvor transkripcije je jedan izbor. Nepoznata ili stara vrednost bezbedno
    # ostaje na Google-u, da postojece instalacije nastave da rade.
    izvor = str(cfg.get("transcription_provider", "google")).lower()
    cfg["transcription_provider"] = (
        izvor if izvor in PROVIDERS else "google"
    )
    script = str(cfg.get("openai_output_script", "latin")).lower()
    cfg["openai_output_script"] = script if script in {"auto", "cyrillic", "latin"} else "latin"
    # Desktop OpenAI diktat koristi latinicu radi usklađenosti sa Androidom.
    if cfg["transcription_provider"] == "openai":
        cfg["openai_output_script"] = "latin"
    cfg["openai_long_recording"] = bool(cfg.get("openai_long_recording", True))
    try:
        cfg["openai_max_seconds"] = min(
            3600, max(60, int(cfg.get("openai_max_seconds", 3600)))
        )
    except (TypeError, ValueError):
        cfg["openai_max_seconds"] = 3600
    cfg["text_model"] = (
        "groq" if str(cfg.get("text_model", "gemini")).lower() == "groq" else "gemini"
    )
    # Istorija je namerno fiksirana na pet stavki, da bude ista kao na telefonu.
    cfg["history_size"] = 5
    try:
        cfg["recorded_seconds"] = max(0.0, float(cfg.get("recorded_seconds", 0.0)))
    except (TypeError, ValueError):
        cfg["recorded_seconds"] = 0.0

    # Glavni prekidac je uklonjen — izabran alat sam znaci "ukljuceno". Ko ga je
    # imao ugasenog, alate treba i ugasiti, da mu se AI ne upali sam od sebe.
    if "polish" in cfg:
        if not cfg.pop("polish"):
            cfg["polish_paragraphs"] = False
            cfg["polish_bullets"] = False
            cfg["polish_dedupe"] = False
            cfg["output_language"] = ""
            if cfg.get("text_style") == "written":
                cfg["text_style"] = "spoken"

    # "raw" je uklonjen: niko ga nije koristio, a bio je treci ishod za isto pitanje.
    if cfg.get("text_style") == "raw":
        cfg["text_style"] = "spoken"

    # Nova dva prekidaca nasleduju stari izbor izgleda samo ako korisnik jos
    # nije upisao zasebne vrednosti. Tako stari "written" ostaje pisan, a
    # podrazumevani "spoken" ostaje malim slovima bez znakova.
    if "lowercase" not in saved:
        cfg["lowercase"] = cfg.get("text_style") != "written"
    if "strip_punctuation" not in saved:
        cfg["strip_punctuation"] = cfg.get("text_style") != "written"

    for mrtvo in ("engine", "credentials_json", "project_id", "location",
                  "model", "punctuation",
                  "polish_tidy", "auto_segment", "max_seconds",
                  "audio_check_low_only", "audio_check_threshold",
                  "polish_emoji", "polish_emoji_rate", "polish_emoji_recent",
                  "join_thousands", "trailing_space", "capitalize_first",
                  "polish_level", "polish_concise", "profanity_filter",
                  "spoken_numbers_to_digits"):
        cfg.pop(mrtvo, None)
    return cfg


def style(cfg) -> str:
    """spoken | written — jedini izvor istine o izgledu teksta."""
    return "written" if cfg.get("text_style") == "written" else "spoken"


def save(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
