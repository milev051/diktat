"""Sklapanje uputstva i pravila oko emotikona."""

import unittest

from dictate import polish


def cfg(**kw):
    osnovno = {
        "polish_api_key": "x", "text_style": "written", "polish_level": "correct",
        "polish_paragraphs": True, "polish_concise": False, "polish_emoji": False,
    }
    osnovno.update(kw)
    return osnovno


class Uputstvo(unittest.TestCase):
    def test_bez_sredjivanja_zabranjuje_interpunkciju(self):
        # Bez ove granice model sredi tekst svejedno — to je izmereno.
        u = polish._uputstvo(cfg(text_style="spoken", polish_concise=True))
        self.assertIn(polish.NE_SREDJUJ, u)
        self.assertNotIn(polish.SREDI, u)

    def test_bez_pasusa_zabranjuje_prelamanje(self):
        u = polish._uputstvo(cfg(polish_paragraphs=False))
        self.assertIn(polish.NE_PASUSI, u)

    def test_bez_sazimanja_zabranjuje_skracivanje(self):
        self.assertIn(polish.NE_SKRACUJ, polish._uputstvo(cfg()))
        self.assertNotIn(polish.NE_SKRACUJ, polish._uputstvo(cfg(polish_concise=True)))

    def test_emotikon_trazi_verno_prepisivanje_kad_niko_ne_menja_reci(self):
        u = polish._uputstvo(cfg(text_style="spoken", polish_emoji=True))
        self.assertIn(polish.EMOTIKONI_VERNO, u)

    def test_emotikon_bez_verno_kad_sazimanje_ionako_menja_reci(self):
        u = polish._uputstvo(cfg(polish_emoji=True, polish_concise=True))
        self.assertNotIn(polish.EMOTIKONI_VERNO, u)

    def test_gustina_emotikona(self):
        # Prvo slovo zadatka se pise veliko, pa se poredi ostatak.
        for rate in ("paragraph", "sentence", "sentence3", "dense"):
            u = polish._uputstvo(cfg(polish_emoji=True, polish_emoji_rate=rate))
            self.assertIn(polish.EMOTIKONI[rate][1:], u)

    def test_nepoznata_gustina_pada_na_pasus(self):
        self.assertEqual(polish.emoji_rate({"polish_emoji_rate": "izmisljeno"}), "paragraph")

    def test_vec_korisceni_znakovi_idu_u_uputstvo(self):
        u = polish._uputstvo(cfg(polish_emoji=True, polish_emoji_recent=["🤝", "🎬"]))
        self.assertIn("🤝 🎬", u)

    def test_bez_alata_nema_poziva(self):
        prazan = cfg(text_style="spoken", polish_paragraphs=False)
        self.assertEqual(polish.tools(prazan), [])
        self.assertEqual(polish.polish("tekst", prazan), "tekst")


class Emotikoni(unittest.TestCase):
    def test_ponovljeni_se_brise_a_prvi_ostaje(self):
        self.assertEqual(polish.bez_ponavljanja("a 🤝 b 🏢 c 🤝 d"), "a 🤝 b 🏢 c d")

    def test_pasusi_prezivljavaju_brisanje(self):
        self.assertEqual(polish.bez_ponavljanja("prvi 🤝\n\ndrugi 🤝 kraj"), "prvi 🤝\n\ndrugi kraj")

    def test_zwj_sekvenca_je_jedan_znak(self):
        self.assertEqual(polish.emoji_list("kolega 👨‍💼"), ["👨‍💼"])

    def test_istorija_pamti_najvise_petnaest(self):
        c = {}
        polish.zapamti_emoji(" ".join(chr(0x1F600 + i) for i in range(20)), c)
        self.assertEqual(len(c["polish_emoji_recent"]), polish.EMOJI_PAMTI)

    def test_ponovljen_znak_ide_na_kraj_istorije(self):
        c = {"polish_emoji_recent": ["🤝", "🎬"]}
        polish.zapamti_emoji("tekst 🤝", c)
        self.assertEqual(c["polish_emoji_recent"], ["🎬", "🤝"])


class ProveraVernosti(unittest.TestCase):
    def test_izmisljena_rec_obara_izlaz(self):
        c = cfg(text_style="spoken", polish_emoji=True)
        self.assertEqual(polish._proveri("bio je dobar", "bio je dobar film 🎬", c), "bio je dobar")

    def test_emotikon_i_interpunkcija_ne_smetaju(self):
        c = cfg(text_style="spoken", polish_emoji=True)
        self.assertEqual(polish._proveri("bio je dobar", "bio je dobar 🎬", c), "bio je dobar 🎬")

    def test_sazimanje_sme_da_menja_reci(self):
        c = cfg(polish_concise=True)
        self.assertEqual(polish._proveri("pa ovaj bio je dobar", "bio je dobar", c), "bio je dobar")


if __name__ == "__main__":
    unittest.main()


class PosleSlusanja(unittest.TestCase):
    """Kad je model vec slusao snimak, sredjivanje bi bilo drugi poziv za isti posao."""

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
        c = cfg(polish_concise=True, polish_emoji=True)
        self.assertEqual(
            sorted(polish.tools(c, vec_sredjeno=True)), ["concise", "emoji", "paragraphs"]
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
