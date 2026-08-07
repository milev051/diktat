import struct
import unittest

from dictate import groq


class GroqTest(unittest.TestCase):
    def test_wav_zaglavlje(self):
        pcm = b"\x00\x01" * 100
        wav = groq.wav_bytes(pcm, 16000)
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:12], b"WAVE")
        self.assertEqual(struct.unpack("<I", wav[24:28])[0], 16000)
        self.assertEqual(struct.unpack("<I", wav[40:44])[0], len(pcm))

    def test_poredi_oba_prepisa(self):
        prompt = groq._merge_prompt(
            "google tekst", "whisper tekst",
            {"text_style": "written", "vocabulary": "AI, API"},
        )
        self.assertIn("google tekst", prompt)
        self.assertIn("whisper tekst", prompt)
        self.assertIn("AI, API", prompt)
        self.assertIn("pravopisno pravilno", prompt)
        self.assertIn("ne dobijaš audio", prompt)

    def test_podrazumevano_ne_ukljucuje_groq(self):
        self.assertFalse(groq.enabled({"groq_enabled": False, "groq_api_key": "x"}))
        self.assertFalse(groq.enabled({"groq_enabled": True, "groq_api_key": ""}))
        self.assertTrue(groq.enabled({"groq_enabled": True, "groq_api_key": "x"}))


if __name__ == "__main__":
    unittest.main()
