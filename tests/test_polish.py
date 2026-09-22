"""Sklapanje uputstva i pravila oko emotikona."""

import unittest
from unittest.mock import patch

from dictate import polish


def cfg(**kw):
    osnovno = {
        "polish_api_key": "x", "text_style": "written",
        "polish_paragraphs": True,
    }
    osnovno.update(kw)
    return osnovno


class Uputstvo(unittest.TestCase):
    def test_prazan_ili_razmak_kljuc_ne_ukljucuje_ai(self):
        self.assertFalse(polish.available({"polish_api_key": ""}))
        self.assertFalse(polish.available({"polish_api_key": "   "}))

    def test_bez_sredjivanja_zabranjuje_interpunkciju(self):
        # Bez ove granice model sredi tekst svejedno — to je izmereno.
        u = polish._uputstvo(cfg(text_style="spoken"))
        self.assertIn(polish.NE_SREDJUJ, u)
        self.assertNotIn(polish.SREDI, u)

    def test_bez_pasusa_zabranjuje_prelamanje(self):
        u = polish._uputstvo(cfg(polish_paragraphs=False))
        self.assertIn(polish.NE_PASUSI, u)

    def test_zabrana_skracivanja_otpada_uz_alat_koji_prepisuje(self):
        self.assertIn(polish.NE_SKRACUJ, polish._uputstvo(cfg()))
        self.assertNotIn(
            polish.NE_SKRACUJ, polish._uputstvo(cfg(polish_bullets=True))
        )

    def test_bez_alata_nema_poziva(self):
        prazan = cfg(text_style="spoken", polish_paragraphs=False)
        self.assertEqual(polish.tools(prazan), [])
        self.assertEqual(polish.polish("tekst", prazan), "tekst")

    def test_model_za_tekst_ima_odvojene_kljuceve(self):
        self.assertTrue(polish.available(cfg(text_model="gemini")))
        self.assertFalse(polish.available(cfg(text_model="groq", groq_api_key="")))
        self.assertTrue(
            polish.available(cfg(text_model="groq", groq_api_key="groq-key"))
        )

    def test_groq_model_se_koristi_za_manipulaciju(self):
        c = cfg(text_model="groq", groq_api_key="groq-key")
        with patch("dictate.groq.manipulate_text", return_value="obrađen tekst") as poziv:
            self.assertEqual(polish.polish("sirov tekst", c), "obrađen tekst")
        self.assertEqual(poziv.call_args.args[0], "sirov tekst")
        self.assertIn(polish.PASUSI, poziv.call_args.args[2])




class ProveraVernosti(unittest.TestCase):
    def test_izmisljena_rec_obara_izlaz(self):
        c = cfg(text_style="spoken")
        self.assertEqual(polish._proveri("bio je dobar", "bio je dobar film", c), "bio je dobar")

    def test_interpunkcija_ne_smeta(self):
        c = cfg(text_style="spoken")
        self.assertEqual(polish._proveri("bio je dobar", "Bio je dobar.", c), "Bio je dobar.")

    def test_izbacivanje_ponavljanja_sme_da_menja_reci(self):
        c = cfg(polish_dedupe=True)
        self.assertEqual(polish._proveri("pa ovaj bio je dobar", "bio je dobar", c), "bio je dobar")


if __name__ == "__main__":
    unittest.main()


class PosleSlusanja(unittest.TestCase):
    """Kad je model vec slusao snimak, sredjivanje bi bilo drugi poziv za isti posao."""

    def test_ispravljanje_ide_uz_sredjivanje(self):
        # Nivo "samo oblikuj" je uklonjen: prekidac se nije mogao dirati, a
        # ispravljanje je ionako deo sredjivanja.
        u = polish._uputstvo(cfg())
        self.assertIn(polish.ISPRAVI, u)
        self.assertNotIn(polish.NE_ISPRAVLJAJ, u)


class BezPrevoda(unittest.TestCase):
    """Prevod je uklonjen: zatecen opis jezika ne sme da ozivi alat."""

    def test_zatecen_kljuc_ne_pravi_alat(self):
        self.assertNotIn("translate", polish.tools(cfg(output_language="makedonski")))

    def test_zatecen_kljuc_ne_pravi_poziv(self):
        c = cfg(text_style="spoken", polish_paragraphs=False,
                output_language="makedonski")
        self.assertEqual(polish.tools(c), [])
        self.assertEqual(polish.polish("tekst", c), "tekst")

    def test_opis_jezika_ne_ulazi_u_uputstvo(self):
        u = polish._uputstvo(cfg(output_language="pola makedonski pola srpski"))
        self.assertNotIn("makedonski", u)


class Tacke(unittest.TestCase):
    """Sazimanje u spisak tacaka, nalik ASD-STE100."""

    def test_tacke_iskljucuju_pasuse(self):
        c = cfg(polish_bullets=True, polish_paragraphs=True)
        self.assertIn("bullets", polish.tools(c))
        self.assertNotIn("paragraphs", polish.tools(c))
        u = polish._uputstvo(c)
        self.assertIn(polish.TACKE, u)
        self.assertNotIn(polish.PASUSI, u)

    def test_bez_zabrane_preformulisanja(self):
        # Prepisivanje recenica je ceo posao ovog alata.
        self.assertNotIn(polish.NE_SKRACUJ, polish._uputstvo(cfg(polish_bullets=True)))

    def test_provera_vernosti_ne_obara_tacke(self):
        c = cfg(text_style="spoken", polish_bullets=True)
        self.assertEqual(
            polish._proveri("pa ovaj bio sam tamo", "- Bio sam tamo.", c), "- Bio sam tamo."
        )

    def test_sam_alat_dovoljan_za_poziv(self):
        c = cfg(text_style="spoken", polish_paragraphs=False, polish_bullets=True)
        self.assertEqual(polish.tools(c), ["bullets"])


class Ponavljanja(unittest.TestCase):
    """Govorna ispravka udvoji frazu; prepoznavanje je prenese doslovno."""

    def test_alat_ulazi_u_uputstvo(self):
        self.assertIn(polish.PONAVLJANJA, polish._uputstvo(cfg(polish_dedupe=True)))

    def test_radi_i_bez_tacaka(self):
        c = cfg(text_style="spoken", polish_paragraphs=False, polish_dedupe=True)
        self.assertEqual(polish.tools(c), ["dedupe"])

    def test_bez_zabrane_preformulisanja(self):
        # Brisanje ponavljanja skida reci — zabrana bi sama sebi protivrecila.
        self.assertNotIn(polish.NE_SKRACUJ, polish._uputstvo(cfg(polish_dedupe=True)))

    def test_provera_vernosti_ne_obara_izlaz(self):
        c = cfg(text_style="spoken", polish_dedupe=True)
        self.assertEqual(
            polish._proveri("i onda i onda sam otisao", "i onda sam otisao", c),
            "i onda sam otisao",
        )

    def test_tacke_traze_vrstu_iskaza(self):
        u = polish._uputstvo(cfg(polish_bullets=True))
        self.assertIn("pitanje ostaje pitanje", u)

    def test_tacke_imaju_konkretnu_granicu_duzine(self):
        # Meko „podeli kad je jasnije" je davalo tacke od 20 reci; izmereno je
        # da tek izricita granica i spisak veznika stvarno dele izjavu.
        u = polish._uputstvo(cfg(polish_bullets=True))
        self.assertIn("dvanaest reči", u)
        self.assertIn("veznikom", u)
