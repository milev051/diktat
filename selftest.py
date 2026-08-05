#!/usr/bin/env python3
"""Snimi nekoliko sekundi i ispisi sta je prepoznato.

Testira mikrofon + prepoznavanje, BEZ hotkey-a i BEZ lepljenja — pa ako ovo radi
a cela aplikacija ne, problem je u dozvolama za taster ili u ubacivanju teksta.

    ./run.sh test         # 5 sekundi
    ./run.sh test 10      # 10 sekundi
"""

import sys
import time

from dictate import audio, config, webstt

BAR = "▁▂▃▄▅▆▇█"


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    cfg = config.load()
    lang = cfg.get("language", "sr-RS")

    print(f"\njezik: {lang}   mikrofon: {audio.default_input_name()}")
    for n in (3, 2, 1):
        print(f"  {n}…", end="", flush=True)
        time.sleep(0.7)
    print(f"\n\n  PRICAJ! ({seconds:.0f}s)\n")

    rec = audio.Recorder(sample_rate=cfg["sample_rate"], device=cfg.get("input_device"))
    rec.start()

    frames = []
    collector = _collect(rec, frames)
    deadline = time.time() + seconds

    text = _transcribe(cfg, lang, collector, deadline, rec, frames)

    rec.close()
    print("\n")
    if text:
        print(f"  PREPOZNATO:  {text}")
    else:
        print("  Nista nije prepoznato.")
        print("  Proveri da li si govorio dovoljno glasno (merac je trebalo da skace).")
    print()
    return 0 if text else 1


def _collect(rec, frames):
    """Vrti komade sa mikrofona do isteka vremena i uz put crta merac nivoa."""

    def gen(deadline):
        for chunk in rec.chunks():
            frames.append(chunk)
            level = min(1.0, rec.level * 3.0)
            bars = BAR[min(int(level * len(BAR)), len(BAR) - 1)] * max(
                1, int(level * 28)
            )
            print(f"\r  {bars:<30}", end="", flush=True)
            yield chunk
            if time.time() >= deadline:
                rec.stop()
                return

    return gen


def _transcribe(cfg, lang, collector, deadline, rec, frames):
    for _ in collector(deadline):
        pass
    rec.stop()
    print("\r  Saljem Google-u…                    ", end="", flush=True)
    text = webstt.recognize(
        b"".join(frames),
        language=lang,
        sample_rate=cfg["sample_rate"],
        key=cfg.get("api_key") or None,
        profanity_filter=bool(cfg.get("profanity_filter", False)),
    )
    return webstt.tidy(text) if cfg.get("capitalize_first", True) else text



if __name__ == "__main__":
    sys.exit(main())
