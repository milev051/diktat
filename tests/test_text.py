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
        # Crtica koja SPAJA dve reci prezivljava; sama nestaje.
        self.assertEqual(webstt.strip_punctuation("crno-beli film"), "crno-beli film")
        self.assertEqual(webstt.strip_punctuation("srpsko-hrvatski i e-mail"),
                         "srpsko-hrvatski i e-mail")
        self.assertEqual(webstt.strip_punctuation("ovo - ono"), "ovo ono")
        self.assertEqual(webstt.strip_punctuation("ovo — ono"), "ovo ono")

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

    def test_valuta_recima_zadrzava_razmak(self):
        # Cela rec se NE lepi uz cifru: "100dolara" izgleda kao greska.
        self.assertEqual(self.primeni("kosta 100 dolara"), "kosta 100 dolara")
        self.assertEqual(self.primeni("kosta 500 dinara"), "kosta 500 dinara")
        self.assertEqual(self.primeni("placa 20 evra"), "placa 20 evra")
        self.assertEqual(self.primeni("stigao za 3 sata"), "stigao za 3 sata")
        self.assertEqual(self.primeni("ima 5 procenata"), "ima 5 procenata")
        self.assertEqual(self.primeni("presao 20 kilometara"), "presao 20 kilometara")

    def test_kratka_oznaka_se_i_dalje_lepi(self):
        for ulaz, izlaz in (("ceka 30 min", "ceka 30min"),
                            ("presao 20 km", "presao 20km"),
                            ("tezi 10 kg", "tezi 10kg"),
                            ("traje 3 h", "traje 3h")):
            self.assertEqual(self.primeni(ulaz), izlaz)

    def test_oznaka_valute_ostaje_sa_razmakom(self):
        # Trocifrena oznaka je kao "5000 RSD" iz korisnickog pravila bez „<".
        self.assertEqual(self.primeni("placa 20 eur"), "placa 20 eur")
        self.assertEqual(self.primeni("kosta 100 usd"), "kosta 100 usd")

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


class VelikoSlovoPosleTacke(unittest.TestCase):
    """Pisani stil znaci veliko slovo na pocetku svake recenice.

    Granica ume da stigne i bez razmaka (model slepi dve recenice), pa razmak i
    veliko slovo idu zajedno. Izuzetak je tacka koja ne zavrsava recenicu:
    godina, redni broj, skracenica, inicijal, i tacka unutar imena fajla.
    """

    def sredi(self, tekst):
        from dictate import webstt
        return webstt.capitalize_sentences(tekst)

    def test_malo_slovo_posle_tacke_se_podize(self):
        self.assertEqual(self.sredi("Okej. sto se tice toga."),
                         "Okej. Sto se tice toga.")

    def test_slepljena_recenica_dobija_razmak(self):
        self.assertEqual(self.sredi("prethodnu.Cetvrta recenica"),
                         "prethodnu. Cetvrta recenica")

    def test_upitnik_i_uzvicnik(self):
        self.assertEqual(self.sredi("Sta je ovo?ne znam!probaj"),
                         "Sta je ovo? Ne znam! Probaj")

    def test_godina_ostaje_malim_slovom(self):
        self.assertEqual(self.sredi("Bilo je 2026. godine u julu."),
                         "Bilo je 2026. godine u julu.")

    def test_redni_broj_ostaje_malim_slovom(self):
        self.assertEqual(self.sredi("Zauzeo je 5. mesto na takmicenju."),
                         "Zauzeo je 5. mesto na takmicenju.")

    def test_skracenica_ostaje_malim_slovom(self):
        for tekst in ("Koristi npr. ovaj pristup.",
                      "Jabuke, kruske itd. sve je tu.",
                      "Zove se dr. petrovic doduse."):
            self.assertEqual(self.sredi(tekst), tekst)

    def test_inicijal_ostaje_malim_slovom(self):
        self.assertEqual(self.sredi("Potpisao je M. petrovic juce."),
                         "Potpisao je M. petrovic juce.")

    def test_ime_fajla_i_domen_ostaju_celi(self):
        for tekst in ("Otvori config.json pa nastavi.",
                      "Idi na google.com i vidi.",
                      "Pise u nuxt.config.ts negde."):
            self.assertEqual(self.sredi(tekst), tekst)

    def test_decimala_i_hiljade_se_ne_diraju(self):
        self.assertEqual(self.sredi("Verzija 3.5 kosta 5.000 dinara."),
                         "Verzija 3.5 kosta 5.000 dinara.")

    def test_prvo_slovo_komada_se_ne_dira(self):
        # Diktat se secka na pauzama; sledeci komad ume da bude nastavak
        # recenice, pa bi veliko slovo tu bilo greska.
        self.assertEqual(self.sredi("nastavak iste recenice"),
                         "nastavak iste recenice")

    def test_novi_red_prezivljava(self):
        self.assertEqual(self.sredi("Prva.\ndruga tacka"),
                         "Prva.\ndruga tacka")

    def test_kvacice_se_podizu(self):
        self.assertEqual(self.sredi("Gotovo je. često se desi."),
                         "Gotovo je. Često se desi.")

    def test_prazan_tekst(self):
        self.assertEqual(self.sredi(""), "")



class SlepljeneReciBezInterpunkcije(unittest.TestCase):
    """Stil „izgovoreno" brise interpunkciju, pa znak izmedju dve reci ne sme
    prosto da nestane: „gotovo je.sada" bi postalo „gotovo jesada".
    """

    def sredi(self, tekst):
        from dictate import webstt
        return webstt.strip_punctuation(tekst)

    def test_tacka_izmedju_reci_postaje_razmak(self):
        self.assertEqual(self.sredi("gotovo je.sada nastavljam"),
                         "gotovo je sada nastavljam")
        self.assertEqual(self.sredi("prethodnu.Cetvrta recenica"),
                         "prethodnu Cetvrta recenica")

    def test_upitnik_uzvicnik_zarez_dvotacka(self):
        self.assertEqual(self.sredi("sta je ovo?ne znam"), "sta je ovo ne znam")
        self.assertEqual(self.sredi("ne moze!probaj"), "ne moze probaj")
        self.assertEqual(self.sredi("prvo,drugo"), "prvo drugo")
        self.assertEqual(self.sredi("evo:ovako"), "evo ovako")

    def test_brojevi_se_ne_diraju(self):
        self.assertEqual(self.sredi("cena je 3,5 dinara"), "cena je 3,5 dinara")
        self.assertEqual(self.sredi("u 10:30 krecem"), "u 10:30 krecem")
        self.assertEqual(self.sredi("Cena je 1.500,25 dinara."),
                         "Cena je 1.500,25 dinara")

    def test_apostrof_i_dalje_spaja(self):
        # „ć'š" mora da ostane jedna rec, zato apostrof NIJE u tom pravilu.
        self.assertEqual(self.sredi("ć'š ti"), "ćš ti")
        self.assertEqual(self.sredi("je l' ovako"), "je l ovako")

    def test_uobicajen_razmak_ostaje_jedan(self):
        self.assertEqual(self.sredi("obicna recenica. druga recenica"),
                         "obicna recenica druga recenica")


class ProcenatPrezivljava(unittest.TestCase):
    """Endpoint vrati „20%" za izgovoreno „dvadeset procenata".

    Brisanje `%` je pojelo jedini trag jedinice, a model to ne moze da vrati:
    izmereno, `gemini-3.5-flash` nad „popusti je 20" vrati „Popust je 20."
    """

    def sredi(self, tekst):
        from dictate import webstt
        return webstt.strip_punctuation(tekst)

    def test_procenat_ostaje(self):
        self.assertEqual(self.sredi("popusti je 20%."), "popusti je 20%")
        self.assertEqual(self.sredi("porez je 20% na sve"), "porez je 20% na sve")

    def test_valutni_znaci_ostaju(self):
        self.assertEqual(self.sredi("kosta 100$ i 20€"), "kosta 100$ i 20€")

    def test_ostali_simboli_se_i_dalje_brisu(self):
        self.assertEqual(self.sredi("ovo je #test & jos"), "ovo je test jos")



class ObicneReciSeNeRazdvajaju(unittest.TestCase):
    """„jednom" je „jedno" + „m" po spisku brojeva i jedinica, pa se lomilo u
    „jedno m". Uz broj napisan recima jedinica mora imati bar dva slova.
    """

    def primeni(self, tekst):
        from dictate import abbrev
        return abbrev.apply(tekst, [])

    def test_jednom_ostaje_celo(self):
        self.assertEqual(self.primeni("uradio sam to jednom"), "uradio sam to jednom")
        self.assertEqual(self.primeni("u jednom trenutku"), "u jednom trenutku")
        self.assertEqual(self.primeni("idemo jednom nedeljno"), "idemo jednom nedeljno")

    def test_ostale_reci_sa_jednoslovnom_oznakom(self):
        for rec in ("stos", "stom", "trim", "dvas", "deseth"):
            self.assertEqual(self.primeni(f"ovo je {rec} ovde"), f"ovo je {rec} ovde")

    def test_razdvajanje_uz_duzu_jedinicu_ostaje(self):
        self.assertEqual(self.primeni("petminuta"), "pet min")
        self.assertEqual(self.primeni("stodinara"), "sto dinara")
        self.assertEqual(self.primeni("trimetara"), "tri metara")
        self.assertEqual(self.primeni("petsati"), "pet sati")
        self.assertEqual(self.primeni("dvadesetkilometara"), "dvadeset kilometara")

    def test_cifra_uz_jednoslovnu_oznaku_i_dalje_radi(self):
        # Cifra ne moze da napravi rec, pa tu razdvajanje ostaje bezbedno.
        self.assertEqual(self.primeni("traje 3 h"), "traje 3h")
        self.assertEqual(self.primeni("dugacko 5 m"), "dugacko 5m")


class PravilnoNadPrekidac(unittest.TestCase):
    """„Pravilno" je precica nad cetiri prekidaca, ne peto podesavanje.

    Svaki od ta cetiri UDALJAVA tekst od pravopisa, pa „pravilno" znaci: sva
    cetiri ugasena.
    """

    def cfg(self, **izmene):
        osnova = {
            "lowercase": True, "strip_punctuation": True,
            "ascii_diacritics": True, "abbreviations": True,
        }
        osnova.update(izmene)
        return osnova

    def test_sve_ukljuceno_nije_pravilno(self):
        from dictate import config
        self.assertFalse(config.pravilno(self.cfg()))

    def test_sve_iskljuceno_jeste_pravilno(self):
        from dictate import config
        self.assertTrue(config.pravilno(self.cfg(
            lowercase=False, strip_punctuation=False,
            ascii_diacritics=False, abbreviations=False,
        )))

    def test_jedan_ukljucen_vise_nije_pravilno(self):
        # Nad-prekidac se IZVODI iz cetiri; rucno paljenje jednog ga mora oboriti,
        # inace bi kvacica u meniju lagala.
        from dictate import config
        for kljuc in config.PRAVILNO_KLJUCEVI:
            c = self.cfg(lowercase=False, strip_punctuation=False,
                         ascii_diacritics=False, abbreviations=False)
            c[kljuc] = True
            self.assertFalse(config.pravilno(c), kljuc)

    def test_ukljucivanje_gasi_sva_cetiri(self):
        from dictate import config
        c = self.cfg()
        config.postavi_pravilno(c, True)
        for kljuc in config.PRAVILNO_KLJUCEVI:
            self.assertFalse(c[kljuc], kljuc)

    def test_iskljucivanje_vraca_ono_sto_je_bilo(self):
        # Ne podrazumevano: `ascii_diacritics` je podrazumevano iskljucen, pa bi
        # povratak na podrazumevano tiho ukinuo izbor onome ko ga drzi upaljenog.
        from dictate import config
        c = self.cfg(ascii_diacritics=True, abbreviations=False)
        config.postavi_pravilno(c, True)
        config.postavi_pravilno(c, False)
        self.assertTrue(c["ascii_diacritics"])
        self.assertFalse(c["abbreviations"])
        self.assertTrue(c["lowercase"])

    def test_dvaput_ukljuceno_ne_gubi_pamcenje(self):
        # Pamti se samo pri PRELASKU; inace bi drugi poziv zapamtio vec ugasena
        # stanja i povratak ne bi vratio nista.
        from dictate import config
        c = self.cfg(ascii_diacritics=True)
        config.postavi_pravilno(c, True)
        config.postavi_pravilno(c, True)
        config.postavi_pravilno(c, False)
        self.assertTrue(c["ascii_diacritics"])

    def test_bez_pamcenja_vraca_podrazumevano(self):
        from dictate import config
        c = self.cfg(lowercase=False, strip_punctuation=False,
                     ascii_diacritics=False, abbreviations=False)
        config.postavi_pravilno(c, False)
        self.assertTrue(c["lowercase"])
        self.assertTrue(c["strip_punctuation"])
        self.assertTrue(c["abbreviations"])
        self.assertFalse(c["ascii_diacritics"])

    def test_pravilan_tekst_prolazi_kroz_pravila_nedirnut(self):
        # Prava provera: uz „pravilno" nasa pravila ne smeju nista da oduzmu.
        from tests.test_pipeline import napravi
        app = napravi(lowercase=False, strip_punctuation=False,
                      ascii_diacritics=False, abbreviations=False)
        ulaz = "Ovo je rečenica. Druga rečenica, sa zarezom!"
        self.assertEqual(app._apply_rules(ulaz), ulaz)
