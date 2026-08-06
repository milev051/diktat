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
        "strip_punctuation": True, "lowercase": True, "join_thousands": True,
    }
    app.cfg.update(kw)
    app._audio_lock = threading.Lock()
    app._audio_parts = {}
    app._audio_seconds = 0.0
    return app


SEKUNDA = b"\x00" * 32000       # 16000 semplova po 2 bajta


class RedosledZvuka(unittest.TestCase):
    def test_delovi_izlaze_hronoloski(self):
        # Segmenti se prepoznaju paralelno, pa stizu van reda; tiket ih vraca.
        app = napravi()
        app._keep_audio(3, b"\x33" + SEKUNDA)
        app._keep_audio(1, b"\x11" + SEKUNDA)
        app._keep_audio(2, b"\x22" + SEKUNDA)
        prvi_bajtovi = [pcm[:1] for pcm, _ in app._take_audio()]
        self.assertEqual(prvi_bajtovi, [b"\x11", b"\x22", b"\x33"])

    def test_granica_zaustavlja_gomilanje(self):
        # Neprekidan rezim ume da traje satima — bez granice bi bafer rastao.
        app = napravi(audio_check_max_seconds=2)
        for tiket in range(1, 6):
            app._keep_audio(tiket, SEKUNDA)
        self.assertEqual(len(app._take_audio()), 2)

    def test_uzimanje_prazni_bafer(self):
        # Inace bi model u sledecoj proveri "cuo" prosli diktat.
        app = napravi()
        app._keep_audio(1, SEKUNDA)
        app._take_audio()
        self.assertEqual(app._take_audio(), [])
        self.assertEqual(app._audio_seconds, 0.0)

    def test_iskljucena_provera_ne_cuva_zvuk(self):
        app = napravi(audio_check=False)
        app._keep_audio(1, SEKUNDA)
        self.assertEqual(app._take_audio(), [])

    def test_prazan_segment_se_ne_pamti(self):
        app = napravi()
        app._keep_audio(1, b"")
        self.assertEqual(app._take_audio(), [])


class KadaSeCekaKraj(unittest.TestCase):
    def test_provera_snimka_odlaze_ubacivanje(self):
        app = napravi()
        self.assertTrue(app._batch())
        self.assertTrue(app._deferred())

    def test_bez_provere_i_bez_modela_tekst_ide_odmah(self):
        app = napravi(audio_check=False)
        self.assertFalse(app._deferred())

    def test_ai_obrada_sama_takodje_odlaze(self):
        app = napravi(audio_check=False, polish=True, polish_tidy=True)
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
