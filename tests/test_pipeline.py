"""Tok diktata: redosled zvuka, praznjenje bafera, kada se ceka kraj.

Aplikacija se pravi preko `__new__` da se ne pokrece rumps petlja — ovde se
proverava sama logika, bez ekrana i bez mikrofona.
"""

import threading
import unittest

from dictate import app as app_mod


def napravi(**kw):
    app = app_mod.DictateApp.__new__(app_mod.DictateApp)
    app.cfg = {
        "sample_rate": 16000, "audio_check": True, "polish_api_key": "x",
        "audio_check_max_seconds": 120, "polish": False,
        "text_style": "spoken", "join_thousands": True,
    }
    app.cfg.update(kw)
    app._audio_lock = threading.Lock()
    app._audio_parts = {}
    app._audio_seconds = {}
    app._formal_lock = threading.Lock()
    app._formal_parts = {}
    app._count_lock = threading.Lock()
    app._pending_by = {}
    app._session_seq = 0
    return app


SEKUNDA = b"\x00" * 32000       # 16000 semplova po 2 bajta


class RedosledZvuka(unittest.TestCase):
    def test_delovi_izlaze_hronoloski(self):
        # Segmenti se prepoznaju paralelno, pa stizu van reda; tiket ih vraca.
        app = napravi()
        app._keep_audio(1, 3, b"\x33" + SEKUNDA)
        app._keep_audio(1, 1, b"\x11" + SEKUNDA)
        app._keep_audio(1, 2, b"\x22" + SEKUNDA)
        prvi_bajtovi = [pcm[:1] for pcm, _ in app._take_audio(1)]
        self.assertEqual(prvi_bajtovi, [b"\x11", b"\x22", b"\x33"])

    def test_granica_zaustavlja_gomilanje(self):
        # Neprekidan rezim ume da traje satima — bez granice bi bafer rastao.
        app = napravi(audio_check_max_seconds=2)
        for tiket in range(1, 6):
            app._keep_audio(1, tiket, SEKUNDA)
        self.assertEqual(len(app._take_audio(1)), 2)

    def test_uzimanje_prazni_bafer(self):
        # Inace bi model u sledecoj proveri "cuo" prosli diktat.
        app = napravi()
        app._keep_audio(1, 1, SEKUNDA)
        app._take_audio(1)
        self.assertEqual(app._take_audio(1), [])
        self.assertEqual(app._audio_seconds, {})

    def test_iskljucena_provera_ne_cuva_zvuk(self):
        app = napravi(audio_check=False)
        app._keep_audio(1, 1, SEKUNDA)
        self.assertEqual(app._take_audio(1), [])

    def test_prazan_segment_se_ne_pamti(self):
        app = napravi()
        app._keep_audio(1, 1, b"")
        self.assertEqual(app._take_audio(1), [])


class DvaDiktataOdjednom(unittest.TestCase):
    """Nov diktat sme da pocne dok se prethodni obradjuje."""

    def test_zvuk_se_ne_mesa_izmedju_sesija(self):
        app = napravi()
        app._keep_audio(1, 1, b"\x11" + SEKUNDA)
        app._keep_audio(2, 2, b"\x22" + SEKUNDA)
        self.assertEqual([p[:1] for p, _ in app._take_audio(1)], [b"\x11"])
        self.assertEqual([p[:1] for p, _ in app._take_audio(2)], [b"\x22"])

    def test_granica_vazi_po_sesiji(self):
        app = napravi(audio_check_max_seconds=2)
        for tiket in range(1, 6):
            app._keep_audio(1, tiket, SEKUNDA)
            app._keep_audio(2, tiket, SEKUNDA)
        self.assertEqual(len(app._take_audio(1)), 2)
        self.assertEqual(len(app._take_audio(2)), 2)

    def test_zavrsene_preskacu_sesiju_koja_jos_snima(self):
        app = napravi()
        app._formal_parts = {1: ["prvi"], 2: ["drugi"]}
        app._pending_by = {1: 0, 2: 0}
        # Sesija 2 je jos na mikrofonu — njen tekst ne sme da krene modelu.
        self.assertEqual(app._zavrsene(aktivna=2), [1])

    def test_zavrsene_cekaju_prepoznavanje(self):
        app = napravi()
        app._formal_parts = {1: ["prvi"]}
        app._pending_by = {1: 1}
        self.assertEqual(app._zavrsene(aktivna=None), [])
        app._pending_by[1] = 0
        self.assertEqual(app._zavrsene(aktivna=None), [1])

    def test_sesije_dobijaju_razlicite_brojeve(self):
        app = napravi()
        import threading as t
        app._session_lock = t.Lock()
        self.assertNotEqual(app._nova_sesija(), app._nova_sesija())


class KadaSeCekaKraj(unittest.TestCase):
    def test_provera_snimka_odlaze_ubacivanje(self):
        app = napravi()
        self.assertTrue(app._batch())
        self.assertTrue(app._deferred())

    def test_bez_provere_i_bez_modela_tekst_ide_odmah(self):
        app = napravi(audio_check=False)
        self.assertFalse(app._deferred())

    def test_ai_obrada_sama_takodje_odlaze(self):
        app = napravi(audio_check=False, polish=True, text_style="written")
        self.assertTrue(app._deferred())


class PravilaNadPasusima(unittest.TestCase):
    def test_prazan_red_prezivljava(self):
        app = napravi()
        out = app._rules_over_paragraphs("Prvi pasus, ovde.\n\nDrugi pasus!")
        self.assertEqual(out, "prvi pasus ovde\n\ndrugi pasus")

    def test_brojevi_ostaju_celi(self):
        app = napravi()
        self.assertEqual(app._rules_over_paragraphs("U 10:30, za 3,5 dinara."), "u 10:30 za 3,5 dinara")


if __name__ == "__main__":
    unittest.main()


class ZavrsnaObrada(unittest.TestCase):
    """Sta se primenjuje POSLE modela kad on sredjuje tekst."""

    def test_kvacice_se_skidaju_ako_je_trazeno(self):
        app = napravi(ascii_diacritics=True)
        self.assertEqual(app._after_model("Juče je bio čas."), "Juce je bio cas.")

    def test_interpunkcija_i_velika_slova_ostaju(self):
        # To je bas posao koji je model dobio — nasa pravila ga ne smeju gasiti.
        app = napravi(text_style="written")
        self.assertEqual(app._after_model("Juče je bio čas."), "Juče je bio čas.")

    def test_hiljade_se_spajaju(self):
        app = napravi()
        self.assertEqual(app._after_model("Cena je 5.000 dinara."), "Cena je 5000 dinara.")
