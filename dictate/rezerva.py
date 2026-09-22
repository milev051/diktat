"""Rezervna kopija zvuka dok diktat traje.

Svaki diktat se usput upisuje u WAV fajl. Kad prepis uspe, fajl se brise.
Kad ne uspe (mreza, zaglavljen servis, pad aplikacije), fajl ostaje, pa se
prepis moze ponoviti iz Podesavanja bez ponovnog diktiranja. Sta nije
iskorisceno brise se samo posle `ROK_SATI`.

Ovo je izricita odluka od 22.09.2026: ranije se glas nigde nije upisivao, ali
je zaglavljen Live strim od 90 s znacio da se sve izgovara iznova. Fajl stoji
samo u ~/Library/Application Support/Diktat/snimci i nikad se ne salje nigde
sam od sebe.
"""

import threading
import time
import wave
from datetime import datetime
from pathlib import Path

FOLDER = Path.home() / "Library" / "Application Support" / "Diktat" / "snimci"
ROK_SATI = 24
# Kraci snimak od ovoga nije vredan cuvanja: to je slucajan pritisak tastera.
NAJKRACE_SEKUNDI = 1.0
ZAGLAVLJE_WAV = 44
# Ispod ovoga je snimak tisina (slucajan pritisak): izmereno 0.002-0.022 na
# tri takva. Namerno nize od GOVOR_PEAK (0.10) iz app.py: tih govor u
# mikrofon MacBook-a ume da bude ispod 0.10, a prepoznat je.
PRAG_TISINE = 0.03


class Snimak:
    """Jedan WAV koji raste dok diktat traje."""

    def __init__(self, putanja: Path, rate: int):
        self.putanja = putanja
        self.rate = rate
        self._lock = threading.Lock()
        self._wav = None
        self.bajtova = 0
        # Najglasniji komad; tih snimak je slucajan pritisak, ne diktat.
        self.vrh = 0.0

    @classmethod
    def novi(cls, rate: int, folder: Path | None = None) -> "Snimak | None":
        folder = folder or FOLDER
        try:
            folder.mkdir(parents=True, exist_ok=True)
            ime = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".wav"
            snimak = cls(folder / ime, rate)
            wav = wave.open(str(snimak.putanja), "wb")
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            snimak._wav = wav
            return snimak
        except OSError as exc:
            # Rezerva je dodatak: diktat radi i kad disk ne da da se pise.
            print(f"[diktat] rezervni snimak nije otvoren: {exc}")
            return None

    def upisi(self, pcm: bytes):
        with self._lock:
            if self._wav is None or not pcm:
                return
            try:
                # `writeframes` posle svakog komada prepravi i zaglavlje, pa je
                # fajl citljiv i kad proces padne usred diktata.
                self._wav.writeframes(pcm)
                self.bajtova += len(pcm)
                self.vrh = max(self.vrh, _vrh(pcm))
            except OSError as exc:
                print(f"[diktat] rezervni snimak: {exc}")
                self._zatvori()

    def _zatvori(self):
        if self._wav is not None:
            try:
                self._wav.close()
            except OSError:
                pass
            self._wav = None

    def zatvori(self):
        """Snimanje je gotovo. Prekratak snimak se odmah brise."""
        with self._lock:
            self._zatvori()
        if self.sekundi < NAJKRACE_SEKUNDI:
            self.obrisi()

    def obrisi(self):
        with self._lock:
            self._zatvori()
        try:
            self.putanja.unlink(missing_ok=True)
        except OSError:
            pass

    @property
    def sekundi(self) -> float:
        return self.bajtova / 2 / float(self.rate or 16000)


def _vrh(pcm: bytes) -> float:
    from .audio import peak
    return peak(pcm)


def ishod(tekst: str, greska: str | None, vrh: float, otkazano: bool):
    """Sta sa rezervnim snimkom posle diktata: (obrisi_snimak, greska).

    Prepoznat tekst se NIKAD ne odbacuje. Prva verzija ovog pravila je
    brisala i tekst kad je vrh bio ispod 0.10, pa diktat tihim glasom nije
    stizao nigde, bez ijedne greske u logu (22.09.2026).
    """
    if (tekst or "").strip() and not greska:
        return True, None                 # uspeo diktat, snimak ne treba
    if otkazano:
        return False, greska              # otkaz ume da bude slucajan, cuva se
    if not (tekst or "").strip() and vrh < PRAG_TISINE:
        return True, None                 # tisina: nema sta da se cuva ni prijavi
    return False, greska


class Sacuvan:
    """Snimak koji je ostao od neuspelog diktata."""

    def __init__(self, putanja: Path):
        self.putanja = putanja

    @property
    def vreme(self) -> datetime:
        try:
            return datetime.strptime(self.putanja.stem[:15], "%Y%m%d-%H%M%S")
        except ValueError:
            return datetime.fromtimestamp(self.putanja.stat().st_mtime)

    def procitaj(self) -> tuple[bytes, int]:
        """PCM i ucestanost. Ne veruje duzini iz zaglavlja: fajl je mogao da
        ostane nedovrsen kad je proces pao."""
        with wave.open(str(self.putanja), "rb") as wav:
            rate = wav.getframerate()
        sirovo = self.putanja.read_bytes()[ZAGLAVLJE_WAV:]
        return sirovo[: len(sirovo) - len(sirovo) % 2], rate

    @property
    def sekundi(self) -> float:
        try:
            velicina = self.putanja.stat().st_size - ZAGLAVLJE_WAV
            with wave.open(str(self.putanja), "rb") as wav:
                rate = wav.getframerate()
            return max(0, velicina) / 2 / float(rate)
        except (OSError, wave.Error, EOFError):
            return 0.0

    def naslov(self) -> str:
        return f"{self.vreme:%d.%m. %H:%M}, {self.sekundi:.0f} s"

    def obrisi(self):
        try:
            self.putanja.unlink(missing_ok=True)
        except OSError:
            pass


def sacuvani(folder: Path | None = None, aktivni=()) -> list[Sacuvan]:
    """Snimci koji cekaju prepis, najnoviji prvi. Stariji od roka se brisu.

    `aktivni` su putanje diktata koji jos traju; oni nisu ostatak.
    """
    folder = folder or FOLDER
    if not folder.exists():
        return []
    granica = time.time() - ROK_SATI * 3600
    ostali = []
    zauzeti = {Path(p) for p in aktivni}
    for putanja in sorted(folder.glob("*.wav"), reverse=True):
        if putanja in zauzeti:
            continue
        try:
            if putanja.stat().st_mtime < granica:
                putanja.unlink(missing_ok=True)
                continue
        except OSError:
            continue
        ostali.append(Sacuvan(putanja))
    return ostali
