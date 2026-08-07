"""Snimanje diktata na disk radi poredjenja zvuka i prepoznatog teksta.

Za svaki diktat pravi:

    2026-08-04_15-31-07.txt        izvestaj: koji segment je dao koji tekst
    2026-08-04_15-31-07-full.wav   ceo diktat, neisecen
    2026-08-04_15-31-07-01.wav     prvi segment
    2026-08-04_15-31-07-02.wav     drugi segment
    ...

Pusti "full" i citaj izvestaj: ako se neka rec cuje a nema je ni u jednom
segmentu, gubi se u prepoznavanju; ako je nema ni u "full" fajlu, gubi se
u snimanju.

Izvestaj se dopisuje kako rezultati stizu, pa redosled linija ne mora da
prati redosled segmenata — svaka linija nosi svoj broj.
"""

import datetime
import threading
import wave
from pathlib import Path


class Session:
    def __init__(self, directory: Path, sample_rate: int):
        self.dir = directory
        self.rate = sample_rate
        self.stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._lock = threading.Lock()
        self._index = 0
        self._covered = 0.0
        self._empty = 0

    # ------------------------------------------------------------------

    def _write_wav(self, name: str, pcm: bytes):
        path = self.dir / name
        with wave.open(str(path), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(self.rate)
            fh.writeframes(pcm)
        return path

    def _log(self, line: str):
        with (self.dir / f"{self.stamp}.txt").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _seconds(self, pcm: bytes) -> float:
        return len(pcm) / 2 / self.rate

    # ------------------------------------------------------------------

    def next_index(self) -> int:
        with self._lock:
            self._index += 1
            return self._index

    def segment(self, index: int, pcm: bytes, text: str, kind="segment"):
        name = f"{self.stamp}-{index:02d}.wav"
        self._write_wav(name, pcm)
        with self._lock:
            self._covered += self._seconds(pcm)
            if not text:
                self._empty += 1
        flag = "" if text else "   <-- PRAZNO, tekst se izgubio"
        self._log(
            f"[{index:02d}] {kind:8} {self._seconds(pcm):5.1f}s  {name}\n"
            f"     {text!r}{flag}"
        )

    def finish(self, pcm: bytes, final_text: str):
        name = f"{self.stamp}-full.wav"
        self._write_wav(name, pcm)
        total = self._seconds(pcm)
        with self._lock:
            covered, empty = self._covered, self._empty
        # Kljucna provera: da li se segmenti sabiraju na ceo diktat. Ako ne,
        # zvuk se gubi pri secenju; ako da a teksta nema, gubi ga prepoznavanje.
        missing = total - covered
        verdict = (
            "sav zvuk je poslat" if abs(missing) < 0.15
            else f"NEDOSTAJE {missing:.1f}s zvuka — gubi se pri secenju"
        )
        self._log(
            f"\n[CEO DIKTAT] {total:5.1f}s  {name}\n"
            f"     segmenti pokrivaju {covered:.1f}s od {total:.1f}s -> {verdict}\n"
            f"     praznih segmenata: {empty}\n"
            f"     sastavljeno: {final_text!r}\n"
            + "-" * 70
        )

    def ai(self, provider: str, google_text: str, prompt: str = "",
           whisper_text: str = "", merged_text: str = "", error: str = "",
           metadata: str = ""):
        """Zapiši ceo AI prolaz, bez API ključeva ili sirovog HTTP payload-a."""
        lines = [
            f"\n[AI PROLAZ] {provider}",
            f"     {metadata}" if metadata else "",
            f"     Google prepis: {google_text!r}",
        ]
        if whisper_text:
            lines.append(f"     Whisper prepis: {whisper_text!r}")
        if prompt:
            lines.extend(["     Prompt:", prompt])
        if merged_text:
            lines.append(f"     Rezultat modela: {merged_text!r}")
        if error:
            lines.append(f"     GREŠKA: {error}")
        self._log("\n".join(lines))

    def final(self, text: str):
        """Zapiši tačno ono što aplikacija na kraju pokušava da ubaci."""
        self._log(f"\n[FINALNI OUTPUT] {text!r}\n" + "-" * 70)


class DebugDump:
    def __init__(self, directory, sample_rate=16000):
        self.dir = Path(directory).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.rate = sample_rate

    def session(self) -> Session:
        return Session(self.dir, self.rate)

    def latest_log(self):
        """Vrati poslednji tekstualni log ili folder ako još nema diktata."""
        logs = list(self.dir.glob("*.txt"))
        return max(logs, key=lambda path: path.stat().st_mtime) if logs else self.dir
