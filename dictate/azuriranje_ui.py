"""Dugme za azuriranje u zaglavlju i provera nove verzije (azuriranje.py).
"""

import threading
import time

from . import azuriranje
from .pomoc import _short_error


class AzuriranjeUI:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    def azur_dostupno(self) -> bool:
        izdanje = self._azur_izdanje
        return izdanje is not None and azuriranje.novije(
            azuriranje.trenutna_verzija(), izdanje.oznaka
        )

    def azur_dugme_stanje(self) -> tuple[str, bool]:
        """Natpis dugmeta u zaglavlju i da li je zeleno.

        Dugme nosi i trenutnu verziju, pa zasebna oznaka verzije ne postoji.
        Pun opis poslednjeg ishoda je u opisu dugmeta (tooltip).
        """
        trenutna = azuriranje.trenutna_verzija() or "?"
        if self._azur_radi:
            return self._azur_status or "Sačekaj…", False
        if self.azur_dostupno():
            return f"Ažuriraj {trenutna} → {self._azur_izdanje.oznaka}", True
        if self._azur_ishod:
            return f"{self._azur_ishod} ({trenutna})", False
        return f"Proveri ažuriranje ({trenutna})", False

    def _tick_azuriranje(self):
        if self._azur_restart and self._recorder is None and not self._starting:
            if self.upis.na_cekanju() == 0:
                self._azur_restart = False
                print(f"[diktat] azurirano na {azuriranje.trenutna_verzija() or '?'}"
                      ", ponovo pokrecem", flush=True)
                # Tastatura ostaje ukljucena: ovaj proces gasi tek nova instanca,
                # a ako se ona ne pokrene, Diktat mora i dalje da radi.
                azuriranje.ponovo_pokreni()
        if (self.cfg.get("update_check", True) and not self._azur_radi
                and time.time() - self._azur_proveren_u > azuriranje.RAZMAK_PROVERE):
            self._azur_proveri(rucno=False)

    def _azur_proveri(self, rucno: bool):
        self._azur_radi = True
        self._azur_proveren_u = time.time()
        if rucno:
            self._azur_status = "Proveravam…"
            self._azur_ishod = ""
        self._azur_dirty = True

        def worker():
            try:
                izdanje = azuriranje.poslednje()
                self._azur_izdanje = izdanje
                trenutna = azuriranje.trenutna_verzija()
                if azuriranje.novije(trenutna, izdanje.oznaka):
                    self._azur_status = f"Dostupna je nova verzija {izdanje.oznaka}."
                else:
                    self._azur_status = f"Imaš najnoviju verziju ({trenutna})."
                    if rucno:
                        self._azur_ishod = "Najnovija verzija"
            except Exception as exc:  # noqa: BLE001
                # Tiha provera bez mreze ne sme da prepise poslednji dobar ishod.
                if rucno or not self._azur_status:
                    self._azur_status = f"Provera nije uspela: {_short_error(exc)}"
                if rucno:
                    self._azur_ishod = "Provera nije uspela"
            finally:
                self._azur_radi = False
                self._azur_dirty = True

        threading.Thread(target=worker, daemon=True).start()

    def _azur_klik(self):
        if self._azur_radi:
            return
        if not self.azur_dostupno():
            self._azur_proveri(rucno=True)
            return
        if self._recorder is not None or self._starting:
            self._azur_status = "Sačekaj da se diktat završi, pa klikni ponovo."
            self._azur_ishod = "Sačekaj kraj diktata"
            self._azur_dirty = True
            return
        izdanje = self._azur_izdanje
        self._azur_radi = True
        self._azur_dirty = True

        def javi(poruka):
            self._azur_status = poruka
            self._azur_dirty = True

        def worker():
            try:
                azuriranje.instaliraj(izdanje, javi=javi)
                javi("Ponovo pokrećem…")
                self._azur_restart = True
            except Exception as exc:  # noqa: BLE001
                javi(f"Ažuriranje nije uspelo: {_short_error(exc)}")
                self._azur_ishod = "Ažuriranje nije uspelo"
            finally:
                self._azur_radi = False
                self._azur_dirty = True

        threading.Thread(target=worker, daemon=True).start()
