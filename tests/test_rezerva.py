"""Rezervni snimak diktata, bez mikrofona."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from dictate import rezerva


class Rezerva(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _snimi(self, sekundi: float) -> rezerva.Snimak:
        snimak = rezerva.Snimak.novi(16000, folder=self.folder)
        komad = b"\x01\x00" * 1600          # 100 ms
        for _ in range(int(sekundi * 10)):
            snimak.upisi(komad)
        return snimak

    def test_neuspeo_diktat_ostaje_i_cita_se(self):
        snimak = self._snimi(2.0)
        snimak.zatvori()
        sacuvani = rezerva.sacuvani(self.folder)
        self.assertEqual(len(sacuvani), 1)
        pcm, rate = sacuvani[0].procitaj()
        self.assertEqual(rate, 16000)
        self.assertEqual(len(pcm), 2 * 16000 * 2)

    def test_citljiv_i_kad_proces_padne_usred_diktata(self):
        # Bez zatvori(): fajl je ostao otvoren kao posle pada aplikacije.
        self._snimi(1.5)
        pcm, _ = rezerva.sacuvani(self.folder)[0].procitaj()
        self.assertEqual(len(pcm), int(1.5 * 16000) * 2)

    def test_uspeo_diktat_se_brise(self):
        snimak = self._snimi(2.0)
        snimak.zatvori()
        snimak.obrisi()
        self.assertEqual(rezerva.sacuvani(self.folder), [])

    def test_prekratak_se_ne_cuva(self):
        self._snimi(0.5).zatvori()
        self.assertEqual(rezerva.sacuvani(self.folder), [])

    def test_stari_se_brisu_sami(self):
        snimak = self._snimi(2.0)
        snimak.zatvori()
        staro = time.time() - (rezerva.ROK_SATI + 1) * 3600
        os.utime(snimak.putanja, (staro, staro))
        self.assertEqual(rezerva.sacuvani(self.folder), [])
        self.assertFalse(snimak.putanja.exists())

    def test_pamti_najglasniji_komad(self):
        # app.py po ovome brise tih snimak: slucajan pritisak nije diktat.
        snimak = rezerva.Snimak.novi(16000, folder=self.folder)
        snimak.upisi(b"\x10\x00" * 1600)
        snimak.upisi((8000).to_bytes(2, "little", signed=True) * 1600)
        self.assertAlmostEqual(snimak.vrh, 8000 / 32768, places=3)
        snimak.obrisi()

    def test_diktat_u_toku_nije_ostatak(self):
        snimak = self._snimi(2.0)
        self.assertEqual(rezerva.sacuvani(self.folder, aktivni=[snimak.putanja]), [])


class Ishod(unittest.TestCase):
    """Sta posle diktata: prepoznat tekst se nikad ne baca."""

    def test_tih_govor_sa_prepisom_prolazi(self):
        # Bas ovo je bila greska: vrh 0.05 je bio "tisina" i tekst je nestajao.
        self.assertEqual(rezerva.ishod("zdravo", None, 0.05, False), (True, None))

    def test_prepis_prolazi_i_uz_sasvim_tih_snimak(self):
        self.assertEqual(rezerva.ishod("zdravo", None, 0.0, False), (True, None))

    def test_tisina_bez_prepisa_se_brise_bez_greske(self):
        self.assertEqual(rezerva.ishod("", "Isteklo vreme", 0.01, False), (True, None))

    def test_govor_bez_prepisa_se_cuva_uz_gresku(self):
        self.assertEqual(rezerva.ishod("", "Isteklo vreme", 0.3, False),
                         (False, "Isteklo vreme"))

    def test_otkazan_se_cuva(self):
        self.assertEqual(rezerva.ishod("", None, 0.3, True), (False, None))


if __name__ == "__main__":
    unittest.main()
