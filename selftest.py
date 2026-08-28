#!/usr/bin/env python3
"""Snimi nekoliko sekundi i ispisi sta je prepoznato — IZABRANIM izvorom.

Testira mikrofon + prepoznavanje, BEZ hotkey-a i BEZ lepljenja — pa ako ovo radi
a cela aplikacija ne, problem je u dozvolama za taster ili u ubacivanju teksta.

    ./run.sh test              # 5 sekundi
    ./run.sh test 20           # 20 sekundi, pravi pauze da proveris duzi diktat
    ./run.sh replay            # pusti POSLEDNJI neuspeo snimak kroz isti put
    ./run.sh replay ~/x.wav    # pusti odredjen snimak

Ranije je ovaj alat uvek zvao Google, sta god da je bilo izabrano u meniju — pa
je greska u drugom izvoru mogla da prodje neprimeceno. Zato sada ide kroz isti
`_recognize` put koji koristi i sama aplikacija.
"""

import sys
import time
import wave
from pathlib import Path

from dictate import audio, config, geministt, openai, webstt

BAR = "▁▂▃▄▅▆▇█"

IMENA = {
    "google": "Google Web Speech",
    "openai": f"OpenAI {openai.MODEL}",
    "gemini_live": f"Gemini {geministt.LIVE_MODEL}",
}


def prepisi(pcm: bytes, cfg) -> str:
    """Isti izbor izvora kao u aplikaciji (`DictateApp._recognize`)."""
    izvor = cfg.get("transcription_provider", "google")
    if izvor == "openai":
        return openai.post_process(openai.recognize(pcm, cfg), cfg)
    if geministt.enabled(cfg):
        return geministt.post_process(geministt.recognize(pcm, cfg), cfg)
    text, _conf = webstt.recognize_full(
        pcm,
        language=cfg.get("language", "sr-RS"),
        sample_rate=cfg["sample_rate"],
        key=cfg.get("api_key") or None,
    )
    return text


def _ispisi(pcm, cfg, sekunde):
    izvor = cfg.get("transcription_provider", "google")
    print(f"\r  Saljem ({IMENA.get(izvor, izvor)})…            ", end="", flush=True)
    poceo = time.monotonic()
    try:
        text = prepisi(pcm, cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"\r  GRESKA: {exc}\n")
        return 1
    trajanje = time.monotonic() - poceo
    print(f"\r  {sekunde:.1f}s zvuka -> prepis za {trajanje:.1f}s\n")
    if text:
        print(f"  PREPOZNATO:  {text}\n")
        # Broj reci je najbrza provera da nije stalo na prvoj pauzi: kratak
        # prepis za dug snimak znaci da se nesto usput izgubilo.
        print(f"  ({len(text.split())} reci na {sekunde:.0f}s zvuka)\n")
        return 0
    print("  Nista nije prepoznato.")
    print("  Proveri da li si govorio dovoljno glasno (merac je trebalo da skace).\n")
    return 1


def snimi(cfg, seconds):
    print(f"\njezik: {cfg.get('language', 'sr-RS')}   mikrofon: {audio.default_input_name()}")
    print(f"izvor: {IMENA.get(cfg.get('transcription_provider', 'google'))}")
    for n in (3, 2, 1):
        print(f"  {n}…", end="", flush=True)
        time.sleep(0.7)
    print(f"\n\n  PRICAJ! ({seconds:.0f}s)   — pravi pauze, tako se testira duzi diktat\n")

    rec = audio.Recorder(sample_rate=cfg["sample_rate"], device=cfg.get("input_device"))
    rec.start()
    frames = []
    deadline = time.time() + seconds
    for chunk in rec.chunks():
        frames.append(chunk)
        level = min(1.0, rec.level * 3.0)
        bars = BAR[min(int(level * len(BAR)), len(BAR) - 1)] * max(1, int(level * 28))
        print(f"\r  {bars:<30}", end="", flush=True)
        if time.time() >= deadline:
            rec.stop()
            break
    rec.close()
    return b"".join(frames)


def poslednji_snimak(cfg):
    folder = Path(cfg.get("pending_dir", "~/Diktat-neuspeli")).expanduser()
    snimci = sorted(folder.glob("*.wav"), key=lambda p: p.stat().st_mtime_ns)
    return snimci[-1] if snimci else None


def replay(argv):
    """Pusti sacuvan snimak kroz isti put — bez ponovnog diktiranja.

    Neuspeli diktati se ionako cuvaju na disk, pa je ovo najbrzi nacin da se
    ista greska ponovi i posmatra: nema mikrofona, nema slucajnosti.
    """
    cfg = config.load()
    if argv:
        putanja = Path(argv[0]).expanduser()
    else:
        putanja = poslednji_snimak(cfg)
        if putanja is None:
            print("Nema sacuvanih snimaka u", cfg.get("pending_dir"))
            return 1
    if not putanja.exists():
        print("Nema fajla:", putanja)
        return 1
    with wave.open(str(putanja), "rb") as w:
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
    cfg["sample_rate"] = rate
    sekunde = len(pcm) / 2 / rate
    print(f"\nsnimak: {putanja}")
    print(f"izvor:  {IMENA.get(cfg.get('transcription_provider', 'google'))}\n")
    return _ispisi(pcm, cfg, sekunde)


def main():
    cfg = config.load()
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    pcm = snimi(cfg, seconds)
    print("\n")
    return _ispisi(pcm, cfg, len(pcm) / 2 / cfg["sample_rate"])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        sys.exit(replay(sys.argv[2:]))
    sys.exit(main())
