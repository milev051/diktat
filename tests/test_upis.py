"""Red za upis: redosled po tiketima, delovi uzivo, istorija."""

import threading
import time
import unittest

from dictate import upis


class Red(unittest.TestCase):
    def napravi(self, ceka_celinu=False):
        self.upisano, self.obrada = [], []
        self.prolaz = threading.Event()
        red = upis.RedUpisa(
            upisi=self.upisano.append,
            upisi_deo=lambda t: self.upisano.append(("deo", t)),
            ceka_celinu=lambda: ceka_celinu,
            za_obradu=lambda s, t: self.obrada.append((s, t)),
            posle=self.prolaz.set,
        )
        red.pokreni()
        return red

    def sacekaj(self, broj):
        rok = time.monotonic() + 1
        while len(self.upisano) < broj and time.monotonic() < rok:
            time.sleep(0.01)

    def test_kasniji_deo_ceka_raniji(self):
        red = self.napravi()
        prvi, drugi = red.novi_tiket(1), red.novi_tiket(1)
        red.predaj(drugi, "drugi ", 1)
        time.sleep(0.05)
        self.assertEqual(self.upisano, [])
        red.predaj(prvi, "prvi ", 1)
        self.sacekaj(2)
        self.assertEqual(self.upisano, ["prvi ", "drugi "])
        self.assertEqual(red.na_cekanju(), 0)

    def test_delovi_uzivo_idu_odmah_i_ne_dupliraju_se(self):
        # Gemini upis tokom snimanja: potvrdjene celine idu cim dodje red,
        # a kraj istog tiketa (prazan tekst) samo zatvori tiket.
        red = self.napravi()
        prvi, drugi = red.novi_tiket(1), red.novi_tiket(2)
        red.predaj_deo(drugi, "drugi ", 2)
        time.sleep(0.05)
        self.assertEqual(self.upisano, [])
        red.predaj(prvi, "prvi ", 1)
        self.sacekaj(2)
        self.assertEqual(self.upisano, ["prvi ", ("deo", "drugi ")])
        red.predaj(drugi, "", 2)
        time.sleep(0.05)
        self.assertEqual(len(self.upisano), 2)
        self.assertEqual(red.na_cekanju(), 0)
        self.assertEqual(red.na_cekanju_sesije(2), 0)

    def test_ai_obrada_dobija_tekst_umesto_upisa(self):
        red = self.napravi(ceka_celinu=True)
        red.predaj(red.novi_tiket(7), " ceo diktat ", 7)
        self.assertTrue(self.prolaz.wait(1))
        self.assertEqual(self.upisano, [])
        self.assertEqual(self.obrada, [(7, "ceo diktat")])

    def test_upisan_tekst_ide_u_istoriju(self):
        red = self.napravi()
        red.predaj(red.novi_tiket(1), "zdravo ", 1)
        self.sacekaj(1)
        self.assertEqual(red.istorija(), ["zdravo"])

    def test_pokvaren_upis_ne_zaustavlja_red(self):
        red = self.napravi()

        def upisi(tekst):
            if tekst.startswith("prvi"):
                raise RuntimeError("polje nije primilo tekst")
            self.upisano.append(tekst)

        red._upisi = upisi
        red.predaj(red.novi_tiket(1), "prvi ", 1)
        red.predaj(red.novi_tiket(1), "drugi ", 1)
        self.sacekaj(1)
        self.assertEqual(self.upisano, ["drugi "])


class Istorija(unittest.TestCase):
    def napravi(self):
        return upis.RedUpisa(lambda t: None, lambda t: None, lambda: False,
                             lambda s, t: None, lambda: None)

    def test_najnoviji_prvi_bez_ponavljanja_najvise_pet(self):
        red = self.napravi()
        for tekst in ("a", "b", "a", "c", "d", "e", "f"):
            red.zapamti(tekst)
        self.assertEqual(red.istorija(), ["f", "e", "d", "c", "a"])

    def test_promena_se_prijavljuje_jednom(self):
        red = self.napravi()
        red.istorija_promenjena()
        red.zapamti("x")
        self.assertTrue(red.istorija_promenjena())
        self.assertFalse(red.istorija_promenjena())


if __name__ == "__main__":
    unittest.main()
