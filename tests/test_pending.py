"""Neuspeli diktati: imena fajlova i sta se brise."""

import tempfile
import unittest
from pathlib import Path

from dictate.pending import PendingStore


class Cuvanje(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = PendingStore(self.dir, 16000, keep=3)

    def test_dva_snimka_u_istoj_sekundi_se_ne_prepisuju(self):
        # Ime samo od vremena je ranije gubilo drugi zapis.
        prvi = self.store.save(b"\x01" * 3200)
        drugi = self.store.save(b"\x02" * 3200)
        self.assertNotEqual(prvi, drugi)
        self.assertEqual(len(self.store.list()), 2)

    def test_brise_se_najstariji_a_ne_prvi_po_imenu(self):
        # Sortiranje po imenu je brisalo pogresan fajl kad brojac razbije azbucni red.
        putanje = [self.store.save(bytes([i]) * 3200) for i in range(5)]
        preostali = self.store.list()
        self.assertEqual(len(preostali), 3)
        self.assertEqual(preostali, putanje[2:])

    def test_ucitava_se_isti_zvuk(self):
        pcm = bytes(range(256)) * 12
        putanja = self.store.save(pcm)
        self.assertEqual(self.store.load(putanja), pcm)

    def test_uklanjanje_radi(self):
        putanja = self.store.save(b"\x01" * 3200)
        self.store.remove(putanja)
        self.assertEqual(self.store.list(), [])

    def test_prazan_snimak_se_ne_cuva(self):
        self.assertIsNone(self.store.save(b""))
        self.assertEqual(self.store.list(), [])

    def test_wav_je_citljiv(self):
        import wave
        putanja = self.store.save(b"\x00\x01" * 1600)
        with wave.open(str(Path(putanja))) as w:
            self.assertEqual(w.getframerate(), 16000)
            self.assertEqual(w.getnchannels(), 1)


if __name__ == "__main__":
    unittest.main()
