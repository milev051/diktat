"""Provera snimka: kada se salje i sta se salje."""

import struct
import unittest

from dictate import listen


def cfg(**kw):
    osnovno = {"polish_api_key": "x", "audio_check": True, "audio_check_low_only": False}
    osnovno.update(kw)
    return osnovno


class KadaSalje(unittest.TestCase):
    def test_iskljuceno_ne_salje(self):
        self.assertFalse(listen.should_check(cfg(audio_check=False), 0.10))

    def test_bez_kljuca_ne_salje(self):
        self.assertFalse(listen.should_check(cfg(polish_api_key=""), 0.10))

    def test_ukljuceno_salje_uvek(self):
        self.assertTrue(listen.should_check(cfg(), 0.99))

    def test_prag_propusta_samo_nisku_pouzdanost(self):
        c = cfg(audio_check_low_only=True)
        self.assertFalse(listen.should_check(c, 0.95))
        self.assertTrue(listen.should_check(c, 0.60))


class Zaglavlje(unittest.TestCase):
    def test_wav_zaglavlje(self):
        pcm = b"\x00\x01" * 100
        w = listen.wav_bytes(pcm, 16000)
        self.assertEqual(w[:4], b"RIFF")
        self.assertEqual(w[8:12], b"WAVE")
        # Velicina podataka mora da odgovara, inace model dobije odsecen zvuk.
        self.assertEqual(struct.unpack("<I", w[40:44])[0], len(pcm))
        self.assertEqual(struct.unpack("<I", w[24:28])[0], 16000)


class Uputstvo(unittest.TestCase):
    def test_pojmovi_idu_modelu(self):
        u = listen._uputstvo("prepis", cfg(vocabulary="AI, Gemini"))
        self.assertIn("AI, Gemini", u)

    def test_prazan_recnik_ne_dodaje_nista(self):
        self.assertNotIn("pojmovi se često", listen._uputstvo("p", cfg(vocabulary="")))

    def test_vise_delova_menja_uputstvo(self):
        jedan = listen._uputstvo("p", cfg(), delova=1)
        vise = listen._uputstvo("p", cfg(), delova=3)
        self.assertIn("snimak govora", jedan)
        self.assertIn("3 uzastopna snimka", vise)
        self.assertIn(listen.VISE_DELOVA.strip(), vise)

    def test_prepis_ulazi_u_uputstvo(self):
        self.assertIn("moj prepis", listen._uputstvo("moj prepis", cfg()))


if __name__ == "__main__":
    unittest.main()


class Sazimanje(unittest.TestCase):
    """Zvuk koji ide modelu: AAC pa FLAC pa WAV."""

    def setUp(self):
        from dictate import flac
        self.flac = flac
        self.pcm = b"\x00\x01" * 16000

    def test_bez_sazimanja_ide_wav(self):
        deo = listen._deo(self.pcm, 16000, compress=False)
        self.assertEqual(deo["inline_data"]["mime_type"], "audio/wav")

    def test_sa_ffmpegom_ide_aac(self):
        if not self.flac.available():
            self.skipTest("nema ffmpeg-a")
        deo = listen._deo(self.pcm, 16000)
        self.assertEqual(deo["inline_data"]["mime_type"], "audio/aac")

    def test_aac_je_visestruko_manji_od_flaca(self):
        if not self.flac.available():
            self.skipTest("nema ffmpeg-a")
        aac = self.flac.encode_aac(self.pcm, 16000)
        flac_ = self.flac.encode(self.pcm, 16000)
        self.assertLess(len(aac), len(flac_))
        # ADTS tok pocinje sinhro-recju 0xFFF.
        self.assertEqual(aac[0], 0xFF)
        self.assertEqual(aac[1] & 0xF0, 0xF0)
