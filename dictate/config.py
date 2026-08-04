"""Konfiguracija — citanje/pisanje config.json u korenu projekta."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULTS = {
    # --- Izbor motora ---
    # "web"   = besplatni Chromium endpoint, bez naloga. Tekst tek po pustanju
    #           tastera (~1.5s), bez interpunkcije. Radi odmah.
    # "cloud" = Google Cloud Speech-to-Text v2. Trazi nalog i kljuc, ali daje
    #           prikaz rec-po-rec uzivo i interpunkciju.
    "engine": "web",
    "web_api_key": "",            # prazno = ugradjeni javni Chromium kljuc
    "capitalize_first": True,     # web motor ne vraca veliko pocetno slovo
    # Na dugom diktatu seci na pauzi i slati delove dok korisnik jos prica.
    "auto_segment": True,
    "segment_after_seconds": 15,  # pre ovoga se nikad ne sece
    "pause_seconds": 0.7,         # koliko tisine znaci "kraj misli"

    # --- Google Cloud (samo za engine "cloud") ---
    "credentials_json": "",       # putanja do service-account .json kljuca
    "project_id": "",             # ako je prazno, cita se iz kljuca
    "location": "global",         # "global" | "eu" | "us-central1" | "europe-west4" ...
    "model": "long",              # "long" | "short" | "chirp_2"
    "language_codes": ["sr-RS"],
    "punctuation": True,

    # --- Audio ---
    "sample_rate": 16000,
    "input_device": None,         # None = sistemski podrazumevani mikrofon
    "max_seconds": 290,           # Google sece stream na 5 min

    # --- Hotkey ---
    "hotkey": "cmd_r",            # cmd_r | cmd_l | alt_r | ctrl_r | f13 ...
    "mode": "hold",               # "hold" = drzi da snimas | "toggle" = pritisni/pritisni
    "min_seconds": 0.35,          # kraci pritisak se tretira kao obican Cmd, ne kao diktat

    # --- Izlaz ---
    "insert_method": "paste",     # "paste" | "type" | "clipboard_only"
    "restore_clipboard": True,
    "show_overlay": True,
    "trailing_space": True,
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Ne mogu da procitam {CONFIG_PATH}: {exc}") from exc
    return cfg


def save(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def resolve_credentials(cfg: dict) -> str:
    """Postavlja GOOGLE_APPLICATION_CREDENTIALS i vraca project_id."""
    path = cfg.get("credentials_json") or ""
    if path:
        expanded = str(Path(path).expanduser())
        if not os.path.exists(expanded):
            raise RuntimeError(f"Kljuc ne postoji: {expanded}")
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = expanded

    project = cfg.get("project_id") or ""
    if not project and path:
        with open(str(Path(path).expanduser()), encoding="utf-8") as fh:
            project = json.load(fh).get("project_id", "")
    if not project:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        raise RuntimeError(
            "Nema project_id. Upisi ga u config.json ili koristi service-account kljuc."
        )
    return project
