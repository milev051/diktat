import unittest

from dictate import apitest


class ProveraKljucava(unittest.TestCase):
    def test_prazni_kljucevi_ne_zovu_mrezu(self):
        result = apitest.check_all({})
        self.assertEqual(len(result), 3)
        self.assertTrue(all("ključ nije podešen" in row for row in result))

