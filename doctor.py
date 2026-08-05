#!/usr/bin/env python3
"""Provera podesavanja: dozvole, mikrofon i veza sa servisom za prepoznavanje.

Pokretanje:  ./run.sh doctor
"""

import sys
import time

from dictate import audio, config, hotkey, webstt

OK = "\033[32m✓\033[0m"
BAD = "\033[31m✗\033[0m"


def main():
    cfg = config.load()
    lang = cfg.get("language", "sr-RS")
    print(f"\nconfig.json: {config.CONFIG_PATH}")
    print(f"jezik: {lang}   hotkey: {cfg.get('hotkey')}   rezim: {cfg.get('mode')}\n")

    print("— Dozvole —")
    if hotkey.accessibility_granted():
        print(f"  {OK} Accessibility (citanje hotkey-a)")
    else:
        print(f"  {BAD} Accessibility NIJE odobren — hotkey nece raditi.")
        print("      System Settings > Privacy & Security > Accessibility")

    print("\n— Mikrofon —")
    izabran = cfg.get("input_device")
    print(f"  podesen: {izabran or 'sistemski podrazumevani'}")
    try:
        audio.refresh_devices()
        rec = audio.Recorder(sample_rate=cfg["sample_rate"], device=izabran)
        rec.start()
        time.sleep(0.4)
        rec.close()
        print(f"  {OK} {audio.current_input_name()}")
        for ime in audio.input_devices():
            print(f"      · {ime}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {BAD} {exc}")
        print("      System Settings > Privacy & Security > Microphone")

    print("\n— Prepoznavanje govora —")
    tisina = b"\x00" * (cfg["sample_rate"] * 2)   # jedna sekunda
    try:
        webstt.recognize(
            tisina,
            language=lang,
            sample_rate=cfg["sample_rate"],
            key=cfg.get("api_key") or None,
        )
        print(f"  {OK} servis odgovara, jezik {lang}")
        print(f"\n  {OK} Sve spremno — pokreni ./run.sh")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  {BAD} {str(exc).strip().splitlines()[0][:110]}")
        print("\n  Servis je nedokumentovan i Google ga moze ugasiti bez najave.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
