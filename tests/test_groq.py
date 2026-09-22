import unittest

from dictate import groq


class GroqTest(unittest.TestCase):
    def test_user_agent_je_aplikacioni(self):
        self.assertEqual(groq.USER_AGENT, "Diktat/1.0")

    def test_bez_kljuca_nema_obrade(self):
        with self.assertRaises(groq.GroqError):
            groq.manipulate_text("tekst", {"groq_api_key": "  "}, "uputstvo")

    def test_poruke_za_http_greske(self):
        self.assertIn("API ključ", groq._http_message(401))
        self.assertIn("429", groq._http_message(429))


if __name__ == "__main__":
    unittest.main()
