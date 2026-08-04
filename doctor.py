#!/usr/bin/env python3
"""Provera podesavanja: dozvole, mikrofon, Google nalog i koji modeli rade za tvoj jezik.

Pokretanje:  ./run.sh doctor
"""

import sys
import time

from dictate import audio, config, hotkey, stt, webstt

# Kandidati koji podrzavaju streaming; probamo ih redom dok neki ne prodje.
CANDIDATES = [
    ("global", "long"),
    ("global", "short"),
    ("eu", "long"),
    ("europe-west4", "chirp_2"),
    ("us-central1", "chirp_2"),
]

OK = "\033[32m✓\033[0m"
BAD = "\033[31m✗\033[0m"
WARN = "\033[33m!\033[0m"


def silence(cfg, seconds=1.0):
    """Jedna sekunda tisine, u komadima od 100 ms."""
    per_chunk = int(cfg["sample_rate"] * 0.1) * 2
    for _ in range(int(seconds * 10)):
        yield b"\x00" * per_chunk


def main():
    cfg = config.load()
    lang = (cfg.get("language_codes") or ["sr-RS"])[0]
    print(f"\nconfig.json: {config.CONFIG_PATH}")
    print(f"jezik: {lang}   hotkey: {cfg.get('hotkey')}   rezim: {cfg.get('mode')}\n")

    print("— Dozvole —")
    if hotkey.accessibility_granted():
        print(f"  {OK} Accessibility (citanje hotkey-a)")
    else:
        print(f"  {BAD} Accessibility NIJE odobren — hotkey nece raditi.")
        print("      System Settings > Privacy & Security > Accessibility")

    print("\n— Mikrofon —")
    try:
        name = audio.default_input_name()
        rec = audio.Recorder(sample_rate=cfg["sample_rate"])
        rec.start()
        time.sleep(0.4)
        rec.close()
        print(f"  {OK} {name}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {BAD} {exc}")
        print("      System Settings > Privacy & Security > Microphone")

    engine = cfg.get("engine", "web")
    if engine == "web":
        return _check_web(cfg, lang)

    print("\n— Google Cloud —")
    try:
        project = config.resolve_credentials(cfg)
        print(f"  {OK} projekat: {project}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {BAD} {exc}")
        print("\n  Uputstvo je u README.md, odeljak 'Google Cloud podesavanje'.")
        print("  Ili se vrati na besplatni motor:  \"engine\": \"web\"")
        return 1

    print(f"\n— Provera modela za {lang} (svaki test posalje 1s tisine) —")
    working = []
    for location, model in CANDIDATES:
        probe = dict(cfg)
        probe["location"] = location
        probe["model"] = model
        label = f"{location:<14} {model:<8}"
        try:
            client = stt.make_client(probe)
            stt.stream(
                client, probe, project, silence(probe),
                on_interim=lambda _t: None, on_final=lambda _t: None,
            )
            print(f"  {OK} {label} radi")
            working.append((location, model))
        except Exception as exc:  # noqa: BLE001
            print(f"  {BAD} {label} {_first_line(exc)}")

    print()
    if not working:
        print(f"  {BAD} Nijedna kombinacija ne radi za {lang}.")
        print("      Proveri da je Speech-to-Text API ukljucen i billing aktivan.")
        return 1

    current = (cfg.get("location"), cfg.get("model"))
    if current in working:
        print(f"  {OK} Trenutno podesenje ({current[0]}/{current[1]}) radi. Sve spremno.")
    else:
        best = working[0]
        print(f"  {WARN} Trenutno podesenje ({current[0]}/{current[1]}) NE radi.")
        print(f"      Prebacujem config.json na {best[0]}/{best[1]}.")
        cfg["location"], cfg["model"] = best
        config.save(cfg)
        print(f"  {OK} Sacuvano.")
    return 0


def _check_web(cfg, lang):
    """Besplatni endpoint — posalje 1s tisine samo da vidi da li odgovara."""
    print("\n— Besplatni Google Web Speech endpoint —")
    print("  (nema naloga, nema kljuca — ali ni prikaza rec-po-rec)")
    pcm = b"".join(silence(cfg))
    try:
        webstt.recognize(
            pcm,
            language=lang,
            sample_rate=cfg["sample_rate"],
            key=cfg.get("web_api_key") or None,
        )
        print(f"  {OK} endpoint odgovara, jezik {lang}")
        print(f"\n  {OK} Sve spremno — pokreni ./run.sh")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  {BAD} {_first_line(exc)}")
        print("\n  Endpoint je nedokumentovan i Google ga moze ugasiti bez najave.")
        print("  Ako je trajno pao, predji na \"engine\": \"cloud\" (vidi README).")
        return 1


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0][:110]


if __name__ == "__main__":
    sys.exit(main())
