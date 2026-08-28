import struct
import unittest

from dictate import openai


class OpenAITest(unittest.TestCase):
    def test_ima_pet_dodatnih_pokusaja(self):
        self.assertEqual(openai.MAX_RETRIES, 5)

    def test_model_i_endpoint(self):
        self.assertEqual(openai.MODEL, "gpt-transcribe")
        self.assertEqual(
            openai.ENDPOINT,
            "https://api.openai.com/v1/audio/transcriptions",
        )

    def test_prompt_bira_pismo(self):
        self.assertIn("ћирилици", openai._prompt("cyrillic"))
        self.assertIn("латиници", openai._prompt("latin"))

    def test_latinica_cuva_brojeve_url_i_engleski(self):
        tekst = "Љубљана, 10:30, 3.14, https://AI.example/ API"
        self.assertEqual(
            openai.to_latin(tekst),
            "Ljubljana, 10:30, 3.14, https://AI.example/ API",
        )

    def test_post_process_ima_dva_nezavisna_prekinaca(self):
        osnovno = {"openai_output_script": "auto", "abbreviations": False}
        self.assertEqual(
            openai.post_process("Zdravo, SVETE!", {**osnovno, "lowercase": False, "strip_punctuation": True}),
            "Zdravo SVETE",
        )
        self.assertEqual(
            openai.post_process("Zdravo, SVETE!", {**osnovno, "lowercase": True, "strip_punctuation": False}),
            "zdravo, svete!",
        )

    def test_wav_zaglavlje(self):
        pcm = b"\x00\x01" * 100
        wav = openai.wav_bytes(pcm, 16000)
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:12], b"WAVE")
        self.assertEqual(struct.unpack("<I", wav[24:28])[0], 16000)
        self.assertEqual(struct.unpack("<I", wav[40:44])[0], len(pcm))

    def test_multipart_ima_jezike_i_model(self):
        body, content_type = openai._multipart(
            {"model": "gpt-transcribe", "languages[]": "sr"},
            "file", b"audio", "diktat.wav", "audio/wav",
        )
        self.assertIn(b'name="model"', body)
        self.assertIn(b'name="languages[]"', body)
        self.assertIn(b"diktat.wav", body)
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))


if __name__ == "__main__":
    unittest.main()
