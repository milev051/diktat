import unittest
from datetime import date

from dictate import utility


class ProcenaKoristi(unittest.TestCase):
    def test_desetodnevni_zbir_i_dnevni_redovi(self):
        cfg = {}
        pocetak = date(2026, 8, 1)
        utility.start(cfg, pocetak)
        utility.set_spent(cfg, 12.0)
        utility.set_typing_cpm(cfg, 200)
        utility.record_text(cfg, "zdravo", pocetak)
        utility.record_audio(cfg, 30, pocetak)
        utility.record_model(cfg, "Google", "web-speech", "transkripcija", 30, pocetak)
        utility.record_model(cfg, "OpenAI", "gpt-transcribe", "transkripcija", 60, pocetak)
        utility.record_text(cfg, "drugi tekst", date(2026, 8, 2))
        utility.record_audio(cfg, 60, date(2026, 8, 2))

        report = utility.report(cfg, date(2026, 8, 2))
        self.assertTrue(report["started"])
        self.assertEqual(report["elapsed_days"], 2)
        self.assertEqual(report["dictations"], 2)
        self.assertEqual(report["characters"], 17)
        self.assertEqual(report["seconds"], 90)
        self.assertEqual(report["typing_cpm"], 200)
        self.assertAlmostEqual(report["typed_minutes"], 0.085)
        self.assertEqual(len(report["days"]), 2)
        self.assertEqual(
            [(row["provider"], row["calls"]) for row in report["models"]],
            [("Google", 1), ("OpenAI", 1)],
        )

    def test_posle_desetog_dana_se_ne_dodaje_novi_dan(self):
        cfg = {}
        pocetak = date(2026, 8, 1)
        utility.start(cfg, pocetak)
        utility.record_text(cfg, "izvan perioda", date(2026, 8, 11))
        utility.record_model(cfg, "OpenAI", "gpt-transcribe", today=date(2026, 8, 11))
        report = utility.report(cfg, date(2026, 8, 11))
        self.assertEqual(report["elapsed_days"], 10)
        self.assertEqual(report["dictations"], 0)
        self.assertEqual(report["models"], [])
        self.assertEqual(len(report["days"]), 10)

    def test_bez_pokretanja_nema_brojenja(self):
        cfg = {}
        utility.record_text(cfg, "ne broji se", date(2026, 8, 1))
        self.assertFalse(utility.report(cfg, date(2026, 8, 1))["started"])
