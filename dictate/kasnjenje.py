"""Kada okvir uzivo pozuti: izgovoren zvuk ceka prepis.

Ranije pravilo (glas u poslednjoj 1 s, a teksta nema 4 s) palilo je zuto i
kad korisnik samo cuti: posle tisine od 4 s dovoljan je jedan sum iznad praga
(dah, klik, buka) da uslov bude ispunjen. Sada se broji koliko je GLASA bilo
od poslednjeg teksta: zuto tek kad ga ima bar GLAS_MIN, kad je prvi glas posle
teksta stariji od CEKANJE i kad se glas i dalje cuje.
Isto pravilo je u Android `Kasnjenje.kt`.
"""

GLAS_MIN = 1.5      # s glasa od poslednjeg teksta
CEKANJE = 4.0       # s od prvog glasa bez teksta
SVEZE = 1.5         # s od poslednjeg glasa


class Kasnjenje:
    def __init__(self):
        self.reset(0.0)

    def reset(self, now: float):
        """Stigao tekst (ili pocinje snimanje): sve od nule."""
        self.glas = 0.0
        self.prvi = None
        self.poslednji = None

    def glas_komad(self, now: float, trajanje: float):
        """Komad zvuka iznad praga tisine, trajanja `trajanje` sekundi."""
        if trajanje <= 0:
            return
        if self.prvi is None:
            self.prvi = now
        self.poslednji = now
        self.glas += trajanje

    def kasni(self, now: float) -> bool:
        return (self.prvi is not None
                and self.glas >= GLAS_MIN
                and now - self.prvi >= CEKANJE
                and now - self.poslednji < SVEZE)
