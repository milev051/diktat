"""Snimci koje prepoznavanje nije primilo — cuvaju se da se ne izgube.

Endpoint je nedokumentovan i moze da zakaze bez najave. Kad se to desi,
izgovoreno ne sme prosto da nestane: snimak ide na disk i moze da se posalje
ponovo iz menija, ili bar preslusa.
"""

import wave
from pathlib import Path

KEEP = 3   # koliko poslednjih neuspelih snimaka drzimo


class PendingStore:
    def __init__(self, directory, sample_rate=16000, keep=KEEP):
        self.dir = Path(directory).expanduser()
        self.rate = sample_rate
        self.keep = keep
        if self.dir.exists():
            # I ranije sačuvani folderi odmah poštuju novi limit.
            self._trim()

    def save(self, pcm: bytes) -> Path | None:
        if not pcm:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        import datetime

        # Milisekunde plus brojac: ime ne sme da zavisi od toga koliko su
        # dva neuspeha razmaknuta, inace se drugi prepise preko prvog.
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]
        path = self.dir / f"{stamp}.wav"
        counter = 1
        while path.exists():
            path = self.dir / f"{stamp}-{counter}.wav"
            counter += 1
        with wave.open(str(path), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(self.rate)
            fh.writeframes(pcm)
        self._trim()
        return path

    def list(self) -> list[Path]:
        """Od najstarijeg ka najnovijem.

        Sortira se po vremenu izmene, ne po imenu: kad se pojavi brojac u imenu
        ("...-930-1.wav"), azbucni redosled se razilazi sa redosledom upisa pa
        bi `_trim` brisao pogresne fajlove.
        """
        if not self.dir.exists():
            return []
        return sorted(self.dir.glob("*.wav"), key=lambda p: p.stat().st_mtime_ns)

    def load(self, path: Path) -> bytes:
        with wave.open(str(path)) as fh:
            return fh.readframes(fh.getnframes())

    def remove(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    def _trim(self) -> None:
        """Drzi samo poslednjih `keep` — inace disk raste bez granice."""
        files = self.list()
        for old in files[: max(0, len(files) - self.keep)]:
            old.unlink(missing_ok=True)
