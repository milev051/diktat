"""Zuto samo kad izgovoren zvuk ceka prepis, ne u tisini."""
import unittest

from dictate.kasnjenje import Kasnjenje


def pusti(k, od, do, glas, korak=0.05):
    t = od
    while t < do:
        if glas:
            k.glas_komad(t, korak)
        t += korak
    return t


class KasnjenjeTest(unittest.TestCase):
    def test_tisina_sa_kratkim_sumom_nije_kasnjenje(self):
        k = Kasnjenje(); k.reset(0)
        pusti(k, 0, 10, False)
        pusti(k, 10, 10.2, True)          # dah ili klik posle duge tisine
        self.assertFalse(k.kasni(10.3))
        pusti(k, 10.3, 20, False)
        self.assertFalse(k.kasni(20))

    def test_govor_bez_teksta_je_kasnjenje(self):
        k = Kasnjenje(); k.reset(0)
        pusti(k, 0, 5, True)
        self.assertTrue(k.kasni(5))

    def test_tisina_posle_govora_gasi_zuto(self):
        k = Kasnjenje(); k.reset(0)
        pusti(k, 0, 5, True)
        self.assertFalse(k.kasni(7))

    def test_tekst_resetuje(self):
        k = Kasnjenje(); k.reset(0)
        pusti(k, 0, 5, True)
        k.reset(5)
        pusti(k, 5, 6, True)
        self.assertFalse(k.kasni(6))


if __name__ == "__main__":
    unittest.main()
