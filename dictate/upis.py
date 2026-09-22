"""Upis teksta u aktivno polje, strogo po redosledu snimanja, i istorija.

`RedUpisa` drzi SVE svoje stanje sam: red, tikete, brojace i istoriju. Ostatak
aplikacije ga koristi samo kroz metode ispod i nikad ne dira njegove
promenljive. Ranije je to stanje bilo zajednicko sa celim DictateApp-om, pa je
greska u jednom delu tiho menjala tekst koji ide u drugi.

Redosled: prepoznavanja teku paralelno i mogu da se zavrse van reda (kratak
drugi snimak lako stigne pre dugog prvog). Zato svaki deo dobije tiket u
trenutku kad se njegov ZVUK zavrsi, a upis ceka na red po tiketu.
"""

import queue
import threading
import traceback
from collections import deque

VELICINA_ISTORIJE = 5


class RedUpisa:
    """Red za upis sa tiketima; radi u svojoj niti.

    upisi(tekst)            upise gotov tekst u aktivno polje
    upisi_deo(tekst)        upise potvrdjenu celinu dok diktat jos traje
    ceka_celinu()           True kad AI obrada ceka kraj diktata
    za_obradu(sesija, t)    preda deo teksta AI obradi umesto upisa
    posle()                 zove se posle svake obrade reda (glavni tok)
    """

    def __init__(self, upisi, upisi_deo, ceka_celinu, za_obradu, posle):
        self._upisi = upisi
        self._upisi_deo = upisi_deo
        self._ceka_celinu = ceka_celinu
        self._za_obradu = za_obradu
        self._posle = posle
        self._red: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._tiket = 0
        self._na_cekanju = 0
        self._po_sesiji: dict[int, int] = {}
        self._istorija: list[str] = []
        self._istorija_promenjena = True

    # ------------------------------------------------------------ tiketi

    def novi_tiket(self, sesija: int) -> int:
        """Redni broj za upis.

        Dodeljuje se kad se ZVUK tog dela zavrsi, ne kad se prepoznavanje
        zavrsi. Mikrofon snima jedno po jedno, pa je taj redosled hronoloski.
        Svaki tiket mora da se preda tacno jednom (`predaj`), inace red stane.
        """
        with self._lock:
            self._tiket += 1
            self._na_cekanju += 1
            self._po_sesiji[sesija] = self._po_sesiji.get(sesija, 0) + 1
            return self._tiket

    def predaj(self, tiket: int, tekst: str, sesija: int):
        """Gotov tekst za tiket; prazan tekst samo pomera red."""
        self._red.put((tiket, tekst, sesija, False))

    def predaj_deo(self, tiket: int, tekst: str, sesija: int):
        """Potvrdjena celina dok diktat traje; tiket ostaje otvoren."""
        if tekst.strip():
            self._red.put((tiket, tekst, sesija, True))

    def na_cekanju(self) -> int:
        """Koliko delova se jos prepoznaje."""
        with self._lock:
            return self._na_cekanju

    def na_cekanju_sesije(self, sesija: int) -> int:
        with self._lock:
            return self._po_sesiji.get(sesija, 0)

    # ------------------------------------------------------------ istorija

    def zapamti(self, tekst: str):
        """Poslednjih pet diktata, najnoviji prvi, bez ponavljanja."""
        cist = tekst.strip()
        if not cist:
            return
        with self._lock:
            if cist in self._istorija:
                self._istorija.remove(cist)
            self._istorija.insert(0, cist)
            del self._istorija[VELICINA_ISTORIJE:]
            self._istorija_promenjena = True

    def istorija(self) -> list[str]:
        with self._lock:
            return list(self._istorija)

    def istorija_promenjena(self) -> bool:
        """Da li je istorija menjana od prethodnog pitanja (pa prozor da se osvezi)."""
        with self._lock:
            bilo = self._istorija_promenjena
            self._istorija_promenjena = False
            return bilo

    # ------------------------------------------------------------ nit

    def pokreni(self):
        threading.Thread(target=self._radi, name="diktat-upis", daemon=True).start()

    def _radi(self):
        zadrzano: dict[int, deque] = {}
        sledeci = 1
        while True:
            tiket, tekst, sesija, deo = self._red.get()
            zadrzano.setdefault(tiket, deque()).append((tekst, sesija, deo))
            while sledeci in zadrzano:
                dogadjaji = zadrzano[sledeci]
                if not dogadjaji:
                    break
                gotov, cija, je_deo = dogadjaji.popleft()
                if je_deo:
                    self._bezbedno(self._upisi_deo, gotov)
                    continue
                del zadrzano[sledeci]
                sledeci += 1
                with self._lock:
                    if self._na_cekanju > 0:
                        self._na_cekanju -= 1
                    if self._po_sesiji.get(cija, 0) > 0:
                        self._po_sesiji[cija] -= 1
                if gotov and self._ceka_celinu():
                    # AI obrada treba da vidi ceo diktat.
                    self._za_obradu(cija, gotov.strip())
                elif gotov:
                    self.zapamti(gotov)
                    self._bezbedno(self._upisi, gotov)
            self._bezbedno(self._posle)

    @staticmethod
    def _bezbedno(posao, *args):
        # Jedan pokvaren upis ne sme da zaustavi red za sve sledece diktate.
        try:
            posao(*args)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
