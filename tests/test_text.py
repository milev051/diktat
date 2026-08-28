"""Pravila nad prepoznatim tekstom."""

import unittest

from dictate import webstt


class Interpunkcija(unittest.TestCase):
    def test_tacka_i_zarez_odlaze(self):
        self.assertEqual(webstt.strip_punctuation("zdravo, kako si?"), "zdravo kako si")

    def test_brojevi_ostaju_celi(self):
        # Zarez je decimalni, dvotacka je satnica — brisanje bi dalo 35 i 1000.
        self.assertEqual(webstt.strip_punctuation("cena 3,5 u 10:00."), "cena 3,5 u 10:00")

    def test_brojcani_separateri_ostaju(self):
        self.assertEqual(
            webstt.strip_punctuation("verzija 2.0, odnos 1/2 i opseg 10-20."),
            "verzija 2.0 odnos 1/2 i opseg 10-20",
        )

    def test_crtica_u_reci_odlazi(self):
        self.assertEqual(webstt.strip_punctuation("crno-beli film"), "crnobeli film")

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

    def test_nova_dva_kljuceva_ostaju(self):
        from dictate import config
        ostalo = config._migrate({"max_seconds": 290, "auto_segment": True, "lowercase": True})
        self.assertNotIn("max_seconds", ostalo)
        self.assertNotIn("auto_segment", ostalo)
        self.assertTrue(ostalo["lowercase"])
        self.assertTrue(ostalo["strip_punctuation"])


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
        self.assertEqual(self.primeni("jebem li ga stvarno"), "jbm li ga stvarno")
        # "da li" se NE skracuje: "da l" izgleda krnje. "je l" je ostalo.
        self.assertEqual(self.primeni("je li ovo jeli da li"), "je l ovo je l da li")
        # Prepoznavanje "svejedno" vraca i rastavljeno, pa oba oblika rade.
        self.assertEqual(self.primeni("svejedno mi je"), "svj mi je")
        self.assertEqual(self.primeni("sve jedno mi je"), "svj mi je")

    def test_znak_manje_pojede_razmak_ispred(self):
        self.assertEqual(self.primeni("traje 15 minuta"), "traje 15min")

    def test_poklapaju_se_samo_cele_reci(self):
        self.assertEqual(self.primeni("neznam nije fraza"), "neznam nije fraza")

    def test_podrazumevane_valute_ostaju_tekst(self):
        self.assertEqual(self.primeni("kosta 100 dolara"), "kosta 100dolara")

    def test_izgovoreni_brojevi_i_jedinice(self):
        self.assertEqual(self.primeni("pet minuta"), "pet min")
        self.assertEqual(self.primeni("petmin"), "pet min")
        self.assertEqual(self.primeni("dvadeset pet sati"), "dvadeset pet sati")
        self.assertEqual(self.primeni("pet dinara"), "pet dinara")
        self.assertEqual(self.primeni("sto dvadeset i pet minuta"), "sto dvadeset i pet min")
        self.assertEqual(self.primeni("dve hiljade trista dinara"), "dve hiljade trista dinara")

    def test_sto_u_vezniku_ne_postaje_sto(self):
        self.assertEqual(self.primeni("zato sto je kasno"), "zato što je kasno")
        self.assertEqual(self.primeni("sto dinara"), "sto dinara")

    def test_brojevi_rade_i_bez_skracivanja_fraza(self):
        from dictate import abbrev
        self.assertEqual(abbrev.apply("pet minuta", []), "pet min")

    def test_tekstualni_brojevi_ostaju_tekstualni(self):
        from dictate import abbrev
        pravila = self.pravila()
        self.assertEqual(
            abbrev.apply("pet minuta petmin 5min", pravila),
            "pet min pet min 5min",
        )

    def test_svi_oblici_minuta_postaju_min(self):
        from dictate import abbrev
        self.assertEqual(self.primeni("1 minut 2 minute 3 minuta"), "1min 2min 3min")
        self.assertEqual(
            abbrev.apply("jedan minut dve minute tri minuta", self.pravila()),
            "jedan min dve min tri min",
        )

    def test_poslednji_red_pobedjuje(self):
        p = self.pravila("fraza=prvo\nfraza=drugo")
        self.assertEqual(self.primeni("fraza", p), "drugo")

    def test_komentar_i_prazan_red_se_preskacu(self):
        p = self.pravila("# ovo je komentar\n\nne znam=nzm")
        self.assertEqual(len(p), 1)

    def test_neispravan_izraz_ne_obara_diktat(self):
        p = self.pravila("~(nezatvorena=x\nne znam=nzm")
        self.assertEqual(self.primeni("ne znam", p), "nzm")


class UkinutGlavniPrekidac(unittest.TestCase):
    """Ko je imao AI ugašen ne sme da ga dobije preko noći."""

    def prevedi(self, staro):
        from dictate import config
        return config._migrate(dict(staro))

    def test_ugasen_ai_gasi_i_alate(self):
        out = self.prevedi({"polish": False, "polish_paragraphs": True,
                            "polish_bullets": True, "text_style": "written"})
        self.assertFalse(out["polish_paragraphs"])
        self.assertFalse(out["polish_bullets"])
        self.assertEqual(out["text_style"], "spoken")

    def test_ukljucen_ai_ostavlja_alate(self):
        out = self.prevedi({"polish": True, "polish_paragraphs": True})
        self.assertTrue(out["polish_paragraphs"])

    def test_kljuc_vise_ne_postoji(self):
        self.assertNotIn("polish", self.prevedi({"polish": True}))
