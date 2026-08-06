"""Pravila nad prepoznatim tekstom."""

import unittest

from dictate import webstt


class Interpunkcija(unittest.TestCase):
    def test_tacka_i_zarez_odlaze(self):
        self.assertEqual(webstt.strip_punctuation("zdravo, kako si?"), "zdravo kako si")

    def test_brojevi_ostaju_celi(self):
        # Zarez je decimalni, dvotacka je satnica — brisanje bi dalo 35 i 1000.
        self.assertEqual(webstt.strip_punctuation("cena 3,5 u 10:00."), "cena 3,5 u 10:00")

    def test_crtica_u_reci_ostaje(self):
        self.assertEqual(webstt.strip_punctuation("crno-beli film"), "crno-beli film")

    def test_crtica_koja_stoji_sama_odlazi(self):
        self.assertEqual(webstt.strip_punctuation("prvi - drugi"), "prvi drugi")

    def test_hiljade_se_spajaju(self):
        self.assertEqual(webstt.join_thousands("5.000 dinara"), "5000 dinara")

    def test_verzija_nije_hiljada(self):
        # Tacka je separator samo ako je prate TACNO tri cifre i broj se zavrsava.
        self.assertEqual(webstt.join_thousands("verzija 2.0 i android 4.4"), "verzija 2.0 i android 4.4")

    def test_vise_tacaka_u_broju(self):
        self.assertEqual(webstt.join_thousands("1.500.000"), "1500000")

    def test_kvacice_u_ascii(self):
        self.assertEqual(webstt.to_ascii("čćžšđ ČĆŽŠĐ"), "cczsdj CCZSDj")


class OdgovorEndpointa(unittest.TestCase):
    def test_bira_najpouzdaniju_alternativu(self):
        telo = (
            '{"result":[]}\n'
            '{"result":[{"alternative":[{"transcript":"losije","confidence":0.4},'
            '{"transcript":"bolje","confidence":0.9}]}]}\n'
        )
        self.assertEqual(webstt._parse(telo), ("bolje", 0.9))

    def test_prazan_odgovor(self):
        self.assertEqual(webstt._parse('{"result":[]}\n'), ("", 0.0))

    def test_neispravna_linija_ne_obara(self):
        telo = 'ovo nije json\n{"result":[{"alternative":[{"transcript":"tekst","confidence":0.8}]}]}'
        self.assertEqual(webstt._parse(telo), ("tekst", 0.8))


if __name__ == "__main__":
    unittest.main()
