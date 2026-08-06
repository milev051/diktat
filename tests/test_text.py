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


class IzborStila(unittest.TestCase):
    """Tri prekidaca su postala jedan izbor; zatecena podesavanja se prevode."""

    def prevedi(self, staro):
        from dictate import config
        return config._migrate(dict(staro))["text_style"]

    def test_mala_slova_postaju_izgovoreno(self):
        self.assertEqual(self.prevedi({"lowercase": True, "strip_punctuation": True}), "spoken")

    def test_ukljucen_ai_sa_sredjivanjem_postaje_sredjeno(self):
        self.assertEqual(self.prevedi({"polish": True, "polish_tidy": True}), "written")

    def test_sirovo_prelazi_u_izgovoreno(self):
        # "raw" je uklonjen — niko ga nije koristio, a bio je treci ishod za
        # isto pitanje. Ko ga je imao, dobija podrazumevano ponasanje.
        self.assertEqual(self.prevedi({"text_style": "raw"}), "spoken")

    def test_postojeci_izbor_se_ne_dira(self):
        self.assertEqual(self.prevedi({"text_style": "written"}), "written")

    def test_mrtvi_kljucevi_se_izbacuju(self):
        from dictate import config
        ostalo = config._migrate({"max_seconds": 290, "auto_segment": True, "lowercase": True})
        for kljuc in ("max_seconds", "auto_segment", "lowercase", "strip_punctuation"):
            self.assertNotIn(kljuc, ostalo)


class Apostrof(unittest.TestCase):
    """Endpoint vraca apostrof u „je l'", „ć'š" — ide sa ostalim znacima."""

    def test_pravi_apostrof(self):
        self.assertEqual(webstt.strip_punctuation("je l' tako"), "je l tako")

    def test_krivi_apostrof(self):
        self.assertEqual(webstt.strip_punctuation("je l’ tako"), "je l tako")

    def test_jednostruki_navodnici(self):
        self.assertEqual(webstt.strip_punctuation("rekao ‘ovako’"), "rekao ovako")

    def test_brojevi_i_dalje_ostaju_celi(self):
        self.assertEqual(webstt.strip_punctuation("cena 3,5 u 10:00"), "cena 3,5 u 10:00")


class Skracenice(unittest.TestCase):
    """Ista pravila kao na Androidu — do sada ih Mac uopste nije imao."""

    def pravila(self, tekst=None):
        from dictate import abbrev
        return abbrev.parse(tekst if tekst is not None else abbrev.default_text())

    def primeni(self, tekst, pravila=None):
        from dictate import abbrev
        return abbrev.apply(tekst, pravila or self.pravila())

    def test_osnovna_zamena(self):
        self.assertEqual(self.primeni("ne znam gde je"), "nzm gde je")

    def test_znak_manje_pojede_razmak_ispred(self):
        self.assertEqual(self.primeni("traje 15 minuta"), "traje 15min")

    def test_poklapaju_se_samo_cele_reci(self):
        self.assertEqual(self.primeni("neznam nije fraza"), "neznam nije fraza")

    def test_regularni_izraz_premesta_valutu(self):
        self.assertEqual(self.primeni("kosta 100 dolara"), "kosta $100")

    def test_poslednji_red_pobedjuje(self):
        p = self.pravila("fraza=prvo\nfraza=drugo")
        self.assertEqual(self.primeni("fraza", p), "drugo")

    def test_komentar_i_prazan_red_se_preskacu(self):
        p = self.pravila("# ovo je komentar\n\nne znam=nzm")
        self.assertEqual(len(p), 1)

    def test_neispravan_izraz_ne_obara_diktat(self):
        p = self.pravila("~(nezatvorena=x\nne znam=nzm")
        self.assertEqual(self.primeni("ne znam", p), "nzm")
