"""Sklapanje uputstva i pravila oko emotikona."""

import unittest

from dictate import polish


def cfg(**kw):
    osnovno = {
        "polish_api_key": "x", "text_style": "written",
        "polish_paragraphs": True, "output_language": "",
    }
    osnovno.update(kw)
    return osnovno


class Uputstvo(unittest.TestCase):
    def test_bez_sredjivanja_zabranjuje_interpunkciju(self):
        # Bez ove granice model sredi tekst svejedno — to je izmereno.
        u = polish._uputstvo(cfg(text_style="spoken", output_language="engleski"))
        self.assertIn(polish.NE_SREDJUJ, u)
        self.assertNotIn(polish.SREDI, u)

    def test_bez_pasusa_zabranjuje_prelamanje(self):
        u = polish._uputstvo(cfg(polish_paragraphs=False))
        self.assertIn(polish.NE_PASUSI, u)

    def test_zabrana_skracivanja_stoji_dok_nema_prevoda(self):
        self.assertIn(polish.NE_SKRACUJ, polish._uputstvo(cfg()))
        self.assertNotIn(
            polish.NE_SKRACUJ, polish._uputstvo(cfg(output_language="engleski"))
        )

    def test_bez_alata_nema_poziva(self):
        prazan = cfg(text_style="spoken", polish_paragraphs=False)
        self.assertEqual(polish.tools(prazan), [])
        self.assertEqual(polish.polish("tekst", prazan), "tekst")




class ProveraVernosti(unittest.TestCase):
    def test_izmisljena_rec_obara_izlaz(self):
        c = cfg(text_style="spoken")
        self.assertEqual(polish._proveri("bio je dobar", "bio je dobar film", c), "bio je dobar")

    def test_interpunkcija_ne_smeta(self):
        c = cfg(text_style="spoken")
        self.assertEqual(polish._proveri("bio je dobar", "Bio je dobar.", c), "Bio je dobar.")

    def test_prevod_sme_da_menja_reci(self):
        c = cfg(output_language="engleski")
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


class PosleSlusanjaNastavak(unittest.TestCase):
    def test_sredjivanje_otpada(self):
        self.assertEqual(polish.tools(cfg(), vec_sredjeno=True), ["paragraphs"])

    def test_bez_ostalih_alata_nema_poziva(self):
        c = cfg(polish_paragraphs=False)
        self.assertEqual(polish.tools(c, vec_sredjeno=True), [])
        self.assertEqual(polish.polish("tekst", c, vec_sredjeno=True), "tekst")

    def test_uputstvo_vise_ne_trazi_sredjivanje(self):
        u = polish._uputstvo(cfg(), vec_sredjeno=True)
        self.assertNotIn(polish.SREDI, u)
        self.assertIn(polish.PASUSI, u)

    def test_ostali_alati_ostaju(self):
        c = cfg(output_language="engleski")
        self.assertEqual(
            sorted(polish.tools(c, vec_sredjeno=True)), ["paragraphs", "translate"]
        )


class Prevod(unittest.TestCase):
    """Slobodan opis jezika; prazno = bez prevoda."""

    def test_prazno_ne_pravi_alat(self):
        self.assertNotIn("translate", polish.tools(cfg(output_language="")))

    def test_opis_ulazi_u_uputstvo(self):
        u = polish._uputstvo(cfg(output_language="pola makedonski pola srpski"))
        self.assertIn("pola makedonski pola srpski", u)

    def test_prevod_sam_dovoljan_za_poziv(self):
        c = cfg(text_style="spoken", polish_paragraphs=False, output_language="makedonski")
        self.assertEqual(polish.tools(c), ["translate"])

    def test_uz_prevod_nema_zabrane_preformulisanja(self):
        # "ne preformulisi" i prevod se iskljucuju — druge reci su ceo posao.
        u = polish._uputstvo(cfg(output_language="engleski"))
        self.assertNotIn(polish.NE_SKRACUJ, u)

    def test_provera_vernosti_ne_obara_prevod(self):
        c = cfg(text_style="spoken", output_language="makedonski")
        self.assertEqual(polish._proveri("bio sam tamo", "бев таму", c), "бев таму")


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
