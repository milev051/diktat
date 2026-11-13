import unittest
from unittest import mock

from dictate import apitest


class _Odgovor:
    def read(self):
        return b'{"models": [], "data": []}'


class ProveraKljucava(unittest.TestCase):
    def test_polje_skida_razmake_i_ne_dira_ostalo(self):
        cfg = {"openai_api_key": "staro", "language": "sr-RS"}
        apitest.apply_fields(cfg, {"openai_api_key": "  novo  "})
        self.assertEqual(cfg["openai_api_key"], "novo")
        self.assertEqual(cfg["language"], "sr-RS")

    def test_prazni_kljucevi_ne_zovu_mrezu(self):
        result = apitest.check_all({})
        self.assertEqual(len(result), 3)
        self.assertTrue(all("ključ nije podešen" in row for row in result))

    def test_provera_salje_user_agent(self):
        vidjeni = []

        def lazn_otvaranje(request, timeout=30):
            vidjeni.append(request.get_header("User-agent"))
            return _Odgovor()

        with mock.patch("dictate.apitest.urllib.request.urlopen", lazn_otvaranje):
            rezultat = apitest.check_all({
                "polish_api_key": "gemini",
                "groq_api_key": "groq",
                "openai_api_key": "openai",
            })

        self.assertEqual(vidjeni, [apitest.USER_AGENT] * 3)
        self.assertTrue(all(red.startswith("✓") for red in rezultat))

