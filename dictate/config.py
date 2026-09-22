"""Konfiguracija — citanje/pisanje config.json u korenu projekta."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

# Kljucevi se NE ugraduju u kod. Repozitorijum se deli, pa bi ugraden kljuc
# znacio da svaka kopija aplikacije trosi tudji nalog, i da kljuc zauvek ostane
# u istoriji commita. Korisnik ga unosi u aplikaciji; cuva se u config.json,
# koji je u .gitignore.

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
    "openai_max_seconds": 3600,
    # Live salje zvuk DOK snimas, ~2,5 MB po minutu; zaboravljen diktat tu ne
    # trosi samo vreme nego i podatke, sve dok neko ne primeti. Zato je granica
    # kratka i ne stoji na ekranu, kao ni ostala polja koja se nameste jednom.
    "gemini_live_max_seconds": 120,    # sigurnosna granica jednog Gemini diktata
    "gemini_live_insert": False,       # potvrđene celine odmah u aktivno polje na Mac-u
    # Okvir sa prepisom dok govoriš. Direktan upis stiže tek kad Gemini potvrdi
    # celinu, pa bez ovoga između dve potvrde nema znaka da aplikacija čuje.
    "live_preview": True,
    "recorded_seconds": 0.0,       # ukupno vreme uhvaćenog zvuka na ovom računaru
    # Maskiranje psovki je uklonjeno kao podesavanje: uvek `pFilter=0`.
    # Podrazumevano je "spoken": mala slova, bez interpunkcije. "written" znaci
    # da model sredjuje tekst — prekidac za to stoji u AI grupi.
    "text_style": "spoken",
    "lowercase": True,             # nezavisno od interpunkcije
    "strip_punctuation": True,     # brojevi tipa 10:30 i 3,5 ostaju čitavi
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
    # „§" (levo od jedinice) kao drugi prekidac. Nije modifikator nego znak, pa
    # se dok je ukljucen guta — inace bi ostavljao „§" u tekstu.
    "hotkey_section": True,
    # „`" (levo od Z na ISO rasporedu) kao treci prekidac; guta se isto kao „§".
    "hotkey_grave": False,
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
    "rezervni_snimak": True,      # zvuk diktata na disku dok prepis ne uspe (dictate/rezerva.py)
    "update_check": True,         # pitaj GitHub za novu verziju pri otvaranju i jednom dnevno
    "show_overlay": False,        # pilula sa vremenom preko ekrana
    "overlay_position": "top-right",

    # --- Formalni rezim (doterivanje jezickim modelom) ---
    "polish_api_key": "",  # Google AI Studio kljuc, unosi se u aplikaciji
    "polish_model": "",           # prazno = gemini-flash-lite-latest
    "text_model": "gemini",       # "gemini" | "groq"
    "polish_prompt": "",          # prazno = ugradjeno uputstvo
    "polish_paragraphs": True,
    # Preuredi u spisak tacaka (nalik ASD-STE100); iskljucuje pasuse.
    "polish_bullets": False,
    # Izbaci slucajno udvojene reci i fraze (govorna ispravka).
    "polish_dedupe": False,    # podeli na pasuse, prazan red izmedju
    "compress_audio": True,       # FLAC preko ffmpeg-a ako ga ima; inace PCM/WAV
    # --- Groq GPT-OSS kao model za obradu teksta ---
    "groq_api_key": "",
    "groq_reasoning_effort": "medium",
    "groq_max_completion_tokens": 2048,
    # Skracenice i nazivi koje endpoint stalno gresi; idu modelu uz snimak.
    "vocabulary": "AI, API, Gemini, Android, iOS, macOS, Google, GitHub, endpoint, FLAC, APK",

    # --- Debug ---
    "debug": False,               # snimaj zvuk i tekst radi poredjenja
    "debug_dir": "~/Diktat-debug",
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
    if "gemini_live_insert" not in saved and saved.get("gemini_live_preview"):
        cfg["gemini_live_insert"] = True
    cfg.pop("gemini_live_preview", None)
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
                  # Prevod i lokalno cuvanje neuspelih snimaka su uklonjeni:
                  # zatecen kljuc bi ostao u config.json i lagao da opcija
                  # postoji.
                  "output_language", "pending_dir",
                  # Provera snimka drugim modelom, uklonjena 22.09.2026
                  # (docs/provera-snimka.md).
                  "audio_check", "audio_check_max_seconds", "groq_enabled",
                  "spoken_numbers_to_digits"):
        cfg.pop(mrtvo, None)
    return cfg


# Cetiri prekidaca koja zajedno odlucuju da li tekst izlazi „pravilno".
# Svaki od njih UDALJAVA tekst od pravopisa, pa „pravilno" znaci: sva cetiri
# ugasena. Redosled je isti kao u meniju i u Config.kt na Androidu.
PRAVILNO_KLJUCEVI = ("lowercase", "strip_punctuation", "ascii_diacritics", "abbreviations")

# Gde se pamti zatecen izbor dok je „pravilno" upaljeno.
_PRE_PRAVILNO = "pravilno_pre"


def pravilno(cfg) -> bool:
    """Da li tekst izlazi pravopisno uredjen: sva cetiri prekidaca ugasena."""
    return not any(bool(cfg.get(k, False)) for k in PRAVILNO_KLJUCEVI)


def postavi_pravilno(cfg, upaljeno: bool) -> None:
    """Upali ili ugasi sva cetiri odjednom.

    Gasenje NE vraca fiksne podrazumevane vrednosti nego bas ono sto je
    korisnik imao pre nego sto je upalio „pravilno". Razlika je stvarna:
    `ascii_diacritics` je podrazumevano iskljucen, pa bi povratak na
    podrazumevano tiho ukinuo izbor onome ko ga drzi upaljenog. Cetiri
    prekidaca su i dalje tu i smeju da se menjaju pojedinacno; ovo je samo
    precica za dva stanja izmedju kojih se najcesce skace.
    """
    if upaljeno:
        if not pravilno(cfg):
            # Zapamti se samo pri PRELASKU, ne pri svakom pozivu: inace bi
            # drugi klik zapamtio vec ugasena stanja i povratak ne bi vratio
            # nista.
            cfg[_PRE_PRAVILNO] = {k: bool(cfg.get(k, False)) for k in PRAVILNO_KLJUCEVI}
        for k in PRAVILNO_KLJUCEVI:
            cfg[k] = False
        return

    staro = cfg.get(_PRE_PRAVILNO) or {}
    for k in PRAVILNO_KLJUCEVI:
        if k in staro:
            cfg[k] = bool(staro[k])
        else:
            # Nista zapamceno (prvo pokretanje ili rucno menjanje): vrati
            # podrazumevano, da gasenje uvek nesto uradi.
            cfg[k] = bool(DEFAULTS[k])
    cfg.pop(_PRE_PRAVILNO, None)


# Alati AI obrade teksta. Prekidac "AI obrada" nije peto podesavanje nego
# precica nad njima, isto kao „Pravilno": u modelu i dalje vazi da izabran alat
# sam po sebi znaci „ukljuceno", pa ne postoji drugi izvor istine koji bi mogao
# da laze.
AI_ALATI = ("polish_paragraphs", "polish_bullets", "polish_dedupe")
_PRE_AI = "ai_pre"


def ai_obrada(cfg) -> bool:
    """Da li je izabran ijedan alat koji model radi nad tekstom."""
    return style(cfg) == "written" or any(bool(cfg.get(k, False)) for k in AI_ALATI)


def postavi_ai_obradu(cfg, upaljeno: bool) -> None:
    """Upali ili ugasi celu grupu; gasenje pamti zatecen izbor."""
    if upaljeno:
        if ai_obrada(cfg):
            return
        staro = cfg.pop(_PRE_AI, None) or {}
        if staro:
            for k in AI_ALATI:
                cfg[k] = bool(staro.get(k, DEFAULTS[k]))
            cfg["text_style"] = staro.get("text_style", "spoken")
        else:
            # Nista zapamceno: upali ono sto je podrazumevano, da paljenje
            # uvek nesto uradi.
            for k in AI_ALATI:
                cfg[k] = bool(DEFAULTS[k])
        return

    if ai_obrada(cfg):
        cfg[_PRE_AI] = {k: bool(cfg.get(k, DEFAULTS[k])) for k in AI_ALATI}
        cfg[_PRE_AI]["text_style"] = style(cfg)
    for k in AI_ALATI:
        cfg[k] = False
    cfg["text_style"] = "spoken"


def style(cfg) -> str:
    """spoken | written — jedini izvor istine o izgledu teksta."""
    return "written" if cfg.get("text_style") == "written" else "spoken"


def save(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
