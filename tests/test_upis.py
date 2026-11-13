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

    def test_privremeni_tekst_i_potvrda_ostaju_u_istom_redu(self):
        events = []
        red = upis.RedUpisa(
            upisi=lambda t: events.append(("normal", t)),
            upisi_deo=lambda t: events.append(("final", t)),
            ceka_celinu=lambda: False,
            za_obradu=lambda s, t: None,
            posle=lambda: None,
            upisi_preview=lambda t: events.append(("preview", t)),
            kraj_live=lambda: events.append(("end", "")),
        )
        red.pokreni()
        tiket = red.novi_tiket(1)
        red.predaj_preview(tiket, "zdra", 1)
        red.predaj_preview(tiket, "zdravo", 1)
        red.predaj_deo(tiket, "Zdravo ", 1)
        red.predaj(tiket, "", 1)
        rok = time.monotonic() + 1
        while len(events) < 4 and time.monotonic() < rok:
            time.sleep(0.01)
        self.assertEqual(events, [
            ("preview", "zdra"), ("preview", "zdravo"),
            ("final", "Zdravo "), ("end", ""),
        ])

    def test_dijagnostika_pokazuje_cekanje_prethodnog_tiketa(self):
        waits = []
        processed = threading.Event()
        red = upis.RedUpisa(
            upisi=lambda t: None, upisi_deo=lambda t: None,
            ceka_celinu=lambda: False, za_obradu=lambda s, t: None,
            posle=lambda: None,
            upisi_preview=lambda t: processed.set(),
            on_wait=lambda session, seconds: waits.append((session, seconds)),
        )
        red.pokreni()
        first, second = red.novi_tiket(1), red.novi_tiket(2)
        red.predaj_preview(second, "čekam", 2)
        time.sleep(0.18)
        red.predaj(first, "", 1)
        self.assertTrue(processed.wait(1))
        self.assertEqual(waits[0][0], 2)
        self.assertGreaterEqual(waits[0][1], 0.15)

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

    def test_najnoviji_prvi_bez_ponavljanja(self):
        red = self.napravi()
        for tekst in ("a", "b", "a", "c", "d", "e", "f"):
            red.zapamti(tekst)
        self.assertEqual(red.istorija(), ["f", "e", "d", "c", "a", "b"])

    def test_istorija_cuva_najvise_sto(self):
        red = self.napravi()
        for broj in range(105):
            red.zapamti(f"t{broj}")
        istorija = red.istorija()
        self.assertEqual(len(istorija), 100)
        self.assertEqual(istorija[0], "t104")
        self.assertEqual(istorija[-1], "t5")

    def test_promena_se_prijavljuje_jednom(self):
        red = self.napravi()
        red.istorija_promenjena()
        red.zapamti("x")
        self.assertTrue(red.istorija_promenjena())
        self.assertFalse(red.istorija_promenjena())


if __name__ == "__main__":
    unittest.main()
