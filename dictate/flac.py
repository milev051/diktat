"""FLAC sazimanje preko ffmpeg-a, ako ga ima na masini.

Endpoint i model primaju FLAC i vracaju isti prepis kao za sirov PCM, a fajl je
36-42% manji. Python nema ugradjen FLAC enkoder, a dodavati zavisnost zbog
ustede nije vredno — zato se koristi `ffmpeg` ako je instaliran, a ako nije,
salje se PCM kao i pre. Usteda ne sme da obori diktat.
"""

import shutil
import subprocess

_ffmpeg = None


def available() -> bool:
    global _ffmpeg
    if _ffmpeg is None:
        _ffmpeg = shutil.which("ffmpeg") or ""
    return bool(_ffmpeg)


def encode(pcm: bytes, sample_rate: int, timeout=20):
    """Vrati FLAC bajtove, ili None ako ffmpeg ne postoji ili je zakazao."""
    if not pcm or not available():
        return None
    try:
        proc = subprocess.run(
            [
                _ffmpeg, "-loglevel", "error",
                "-f", "s16le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0",
                "-c:a", "flac", "-f", "flac", "pipe:1",
            ],
            input=pcm,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 - nedostupan, spor, sta god
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout
