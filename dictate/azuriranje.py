"""Azuriranje Mac aplikacije iz GitHub izdanja.

Isti izvor kao na telefonu: poslednje izdanje sa milev051/diktat. Telefon iz
njega uzima APK, a Mac izvorni kod te oznake. Kod se raspakuje u instaliranu
kopiju (~/Library/Application Support/Diktat/app), podesavanja i kljucevi
ostaju, a aplikacija se ponovo pokrene u istom procesu.

Bundle u /Applications se namerno ne dira: svaki novi potpis ponistava
dozvole za Accessibility i Mikrofon, pa bi posle svakog azuriranja hotkey
prestao da radi dok se dozvola ne da iznova.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

IZDANJA = "https://api.github.com/repos/milev051/diktat/releases/latest"
DOM = Path.home() / "Library" / "Application Support" / "Diktat"
INSTALIRANO = DOM / "app"
KOREN = Path(__file__).resolve().parent.parent
FAJL_VERZIJE = "VERZIJA"
# Isti spisak koji `make_app.sh install` kopira.
SADRZAJ = ("dictate", "run.py", "doctor.py", "selftest.py",
           "requirements.txt", "config.example.json")
# Jednom dnevno, kao i pri pokretanju.
RAZMAK_PROVERE = 24 * 3600
_GIT_VERZIJA = None


class Izdanje:
    def __init__(self, oznaka: str, naslov: str, arhiva: str):
        self.oznaka = oznaka
        self.naslov = naslov
        self.arhiva = arhiva


def instalirana_kopija() -> bool:
    """Azurira se samo kopija iz /Applications. Folder projekta ide kroz git."""
    try:
        return KOREN.resolve() == INSTALIRANO.resolve()
    except OSError:
        return False


def trenutna_verzija() -> str:
    try:
        return (KOREN / FAJL_VERZIJE).read_text(encoding="utf-8").strip()
    except OSError:
        pass
    # Razvojna kopija nema fajl VERZIJA; njena verzija je poslednja oznaka u
    # gitu. Pita se jednom, jer se ovo zove pri svakom osvezavanju prozora.
    global _GIT_VERZIJA
    if _GIT_VERZIJA is None:
        _GIT_VERZIJA = ""
        if not instalirana_kopija() and (KOREN / ".git").exists():
            try:
                _GIT_VERZIJA = subprocess.run(
                    ["git", "-C", str(KOREN), "describe", "--tags", "--abbrev=0"],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
    return _GIT_VERZIJA


def _zahtev(adresa: str, timeout: float):
    req = urllib.request.Request(adresa, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Diktat-Mac",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def iz_odgovora(telo: str) -> Izdanje:
    koren = json.loads(telo)
    oznaka = str(koren.get("tag_name") or "").strip()
    if not oznaka:
        raise ValueError("Izdanje nema oznaku verzije")
    arhiva = str(koren.get("tarball_url") or "").strip()
    if not arhiva:
        raise ValueError(f"Izdanje {oznaka} nema arhivu koda")
    return Izdanje(oznaka, str(koren.get("name") or oznaka), arhiva)


def poslednje(timeout: float = 15) -> Izdanje:
    with _zahtev(IZDANJA, timeout) as odgovor:
        return iz_odgovora(odgovor.read().decode("utf-8"))


def _brojevi(verzija: str) -> list[int]:
    brojevi, tekuci = [], ""
    for znak in verzija:
        if znak.isdigit():
            tekuci += znak
        elif tekuci:
            brojevi.append(int(tekuci))
            tekuci = ""
    if tekuci:
        brojevi.append(int(tekuci))
    return brojevi


def novije(trenutna: str, izdanje: str) -> bool:
    """„1.9" je starije od „1.11", pa se poredi broj po broj, ne kao tekst.

    Nepoznata trenutna verzija (instalacija bez fajla VERZIJA) se tretira kao
    zastarela, da bi se jednim azuriranjem uvela u red.
    """
    leva, desna = _brojevi(trenutna), _brojevi(izdanje)
    if not leva:
        return bool(desna)
    for i in range(max(len(leva), len(desna))):
        a = leva[i] if i < len(leva) else 0
        b = desna[i] if i < len(desna) else 0
        if a != b:
            return b > a
    return False


def _raspakuj(sadrzaj: bytes, cilj: Path) -> Path:
    """GitHub arhiva ima jedan koreni folder (milev051-diktat-<sha>)."""
    with tarfile.open(fileobj=io.BytesIO(sadrzaj), mode="r:gz") as arhiva:
        try:
            arhiva.extractall(cilj, filter="data")
        except TypeError:
            # Python stariji od 3.12 nema `filter`; arhiva je sa GitHub-a.
            arhiva.extractall(cilj)
    folderi = [p for p in cilj.iterdir() if p.is_dir()]
    if len(folderi) != 1:
        raise ValueError("Arhiva izdanja nema ocekivan oblik")
    izvor = folderi[0]
    for ime in ("run.py", "dictate"):
        if not (izvor / ime).exists():
            raise ValueError(f"U izdanju nema {ime}")
    return izvor


def instaliraj(izdanje: Izdanje, javi=lambda _poruka: None) -> None:
    """Preuzmi kod izdanja i zameni instaliranu kopiju. Ne restartuje."""
    if not instalirana_kopija():
        raise RuntimeError(
            "Ovo je razvojna kopija iz foldera projekta. Azuriraj je sa git pull, "
            "pa pokreni ./make_app.sh install."
        )
    javi(f"Preuzimam {izdanje.oznaka}…")
    with _zahtev(izdanje.arhiva, 60) as odgovor:
        sadrzaj = odgovor.read()

    radni = Path(tempfile.mkdtemp(prefix="azuriranje-", dir=DOM))
    try:
        izvor = _raspakuj(sadrzaj, radni / "arhiva")
        novo = radni / "app"
        novo.mkdir()
        for ime in SADRZAJ:
            putanja = izvor / ime
            if putanja.is_dir():
                shutil.copytree(putanja, novo / ime)
            elif putanja.exists():
                shutil.copy2(putanja, novo / ime)

        stari_zahtevi = (INSTALIRANO / "requirements.txt")
        novi_zahtevi = (novo / "requirements.txt")
        if novi_zahtevi.exists() and (
            not stari_zahtevi.exists()
            or stari_zahtevi.read_bytes() != novi_zahtevi.read_bytes()
        ):
            javi("Instaliram nove biblioteke…")
            rezultat = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "-r", str(novi_zahtevi)],
                capture_output=True, text=True, timeout=600,
            )
            if rezultat.returncode != 0:
                poslednja = (rezultat.stderr or rezultat.stdout).strip().splitlines()
                raise RuntimeError(
                    "pip nije uspeo: " + (poslednja[-1] if poslednja else "nepoznata greska")
                )

        # Podesavanja i kljucevi prezivljavaju azuriranje.
        podesavanja = INSTALIRANO / "config.json"
        if podesavanja.exists():
            shutil.copy2(podesavanja, novo / "config.json")
        (novo / FAJL_VERZIJE).write_text(izdanje.oznaka + "\n", encoding="utf-8")

        # Zamena je dva preimenovanja u istom folderu, pa nema trenutka u kom
        # instalirana kopija postoji samo napola.
        staro = radni / "staro"
        os.replace(INSTALIRANO, staro)
        try:
            os.replace(novo, INSTALIRANO)
        except OSError:
            os.replace(staro, INSTALIRANO)
            raise
    finally:
        shutil.rmtree(radni, ignore_errors=True)


def ponovo_pokreni() -> None:
    """Zameni ovaj proces novim kodom. PID ostaje isti, pa i dozvole i ikonica."""
    sys.stdout.flush()
    sys.stderr.flush()
    # Stara radna putanja je obrisana zajedno sa starom kopijom.
    os.chdir(INSTALIRANO)
    os.execv(sys.executable, [sys.executable, str(INSTALIRANO / "run.py")])
