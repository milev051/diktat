"""Tok diktata: redosled zvuka, praznjenje bafera, kada se ceka kraj.

Aplikacija se pravi preko `__new__` da se ne pokrece rumps petlja — ovde se
proverava sama logika, bez ekrana i bez mikrofona.
"""

import threading
import unittest

from dictate import app as app_mod


def napravi(**kw):
    app = app_mod.DictateApp.__new__(app_mod.DictateApp)
    app.cfg = {
        "sample_rate": 16000, "audio_check": True, "polish_api_key": "x",
        "audio_check_max_seconds": 120, "polish_paragraphs": False,
        "text_style": "spoken", "join_thousands": True,
        "lowercase": True, "strip_punctuation": True,
    }
    app.cfg.update(kw)
    if "lowercase" not in kw:
        app.cfg["lowercase"] = app.cfg["text_style"] != "written"
    if "strip_punctuation" not in kw:
        app.cfg["strip_punctuation"] = app.cfg["text_style"] != "written"
    app._audio_lock = threading.Lock()
    app._audio_parts = {}
    app._audio_seconds = {}
    app._formal_lock = threading.Lock()
    app._formal_parts = {}
    app._count_lock = threading.Lock()
    app._pending_by = {}
    app._session_seq = 0
    return app


SEKUNDA = b"\x00" * 32000       # 16000 semplova po 2 bajta


class RedosledZvuka(unittest.TestCase):
    def test_delovi_izlaze_hronoloski(self):
        # Segmenti se prepoznaju paralelno, pa stizu van reda; tiket ih vraca.
        app = napravi()
        app._keep_audio(1, 3, b"\x33" + SEKUNDA)
        app._keep_audio(1, 1, b"\x11" + SEKUNDA)
        app._keep_audio(1, 2, b"\x22" + SEKUNDA)
        prvi_bajtovi = [pcm[:1] for pcm, _ in app._take_audio(1)]
        self.assertEqual(prvi_bajtovi, [b"\x11", b"\x22", b"\x33"])

    def test_granica_zaustavlja_gomilanje(self):
        # Neprekidan rezim ume da traje satima — bez granice bi bafer rastao.
        app = napravi(audio_check_max_seconds=2)
        for tiket in range(1, 6):
            app._keep_audio(1, tiket, SEKUNDA)
        self.assertEqual(len(app._take_audio(1)), 2)

    def test_uzimanje_prazni_bafer(self):
        # Inace bi model u sledecoj proveri "cuo" prosli diktat.
        app = napravi()
        app._keep_audio(1, 1, SEKUNDA)
        app._take_audio(1)
        self.assertEqual(app._take_audio(1), [])
        self.assertEqual(app._audio_seconds, {})

    def test_iskljucena_provera_ne_cuva_zvuk(self):
        app = napravi(audio_check=False)
        app._keep_audio(1, 1, SEKUNDA)
        self.assertEqual(app._take_audio(1), [])

    def test_prazan_segment_se_ne_pamti(self):
        app = napravi()
        app._keep_audio(1, 1, b"")
        self.assertEqual(app._take_audio(1), [])


class DvaDiktataOdjednom(unittest.TestCase):
    """Nov diktat sme da pocne dok se prethodni obradjuje."""

    def test_zvuk_se_ne_mesa_izmedju_sesija(self):
        app = napravi()
        app._keep_audio(1, 1, b"\x11" + SEKUNDA)
        app._keep_audio(2, 2, b"\x22" + SEKUNDA)
        self.assertEqual([p[:1] for p, _ in app._take_audio(1)], [b"\x11"])
        self.assertEqual([p[:1] for p, _ in app._take_audio(2)], [b"\x22"])

    def test_granica_vazi_po_sesiji(self):
        app = napravi(audio_check_max_seconds=2)
        for tiket in range(1, 6):
            app._keep_audio(1, tiket, SEKUNDA)
            app._keep_audio(2, tiket, SEKUNDA)
        self.assertEqual(len(app._take_audio(1)), 2)
        self.assertEqual(len(app._take_audio(2)), 2)

    def test_zavrsene_preskacu_sesiju_koja_jos_snima(self):
        app = napravi()
        app._formal_parts = {1: ["prvi"], 2: ["drugi"]}
        app._pending_by = {1: 0, 2: 0}
        # Sesija 2 je jos na mikrofonu — njen tekst ne sme da krene modelu.
        self.assertEqual(app._zavrsene(aktivna=2), [1])

    def test_zavrsene_cekaju_prepoznavanje(self):
        app = napravi()
        app._formal_parts = {1: ["prvi"]}
        app._pending_by = {1: 1}
        self.assertEqual(app._zavrsene(aktivna=None), [])
        app._pending_by[1] = 0
        self.assertEqual(app._zavrsene(aktivna=None), [1])

    def test_sesije_dobijaju_razlicite_brojeve(self):
        app = napravi()
        import threading as t
        app._session_lock = t.Lock()
        self.assertNotEqual(app._nova_sesija(), app._nova_sesija())


class KadaSeCekaKraj(unittest.TestCase):
    def test_provera_snimka_odlaze_ubacivanje(self):
        app = napravi()
        self.assertTrue(app._batch())
        self.assertTrue(app._deferred())

    def test_groq_provera_odlaze_ubacivanje(self):
        app = napravi(audio_check=False, groq_enabled=True, groq_api_key="x")
        self.assertTrue(app._batch())
        self.assertTrue(app._deferred())

    def test_groq_bez_kljuceva_ne_odlaze(self):
        app = napravi(audio_check=False, groq_enabled=True, groq_api_key="")
        self.assertFalse(app._batch())

    def test_openai_je_jedini_izvor_transkripcije(self):
        app = napravi(
            transcription_provider="openai",
            audio_check=True,
            groq_enabled=True,
            groq_api_key="x",
        )
        self.assertFalse(app._batch())
        self.assertFalse(app._deferred())

    def test_bez_provere_i_bez_alata_tekst_ide_odmah(self):
        app = napravi(audio_check=False)
        self.assertFalse(app._deferred())

    def test_izabran_alat_sam_po_sebi_pali_ai(self):
        # Glavnog prekidaca nema: izabran alat znaci da se AI koristi.
        app = napravi(audio_check=False, polish_paragraphs=True)
        self.assertTrue(app._deferred())

    def test_bez_kljuca_nema_ai_ja_ma_sta_bilo_izabrano(self):
        app = napravi(audio_check=False, polish_paragraphs=True, polish_api_key="")
        self.assertFalse(app._deferred())


class OpenAiGranica(unittest.TestCase):
    def test_dugi_openai_diktat_ima_sigurnosni_limit(self):
        app = napravi(
            transcription_provider="openai",
            openai_long_recording=True,
            openai_max_seconds=3600,
            continuous=False,
            max_request_seconds=30,
        )
        self.assertEqual(app._limit_seconds(), 3600)

    def test_openai_moze_da_se_vrati_na_kratak_rezim(self):
        app = napravi(
            transcription_provider="openai",
            openai_long_recording=False,
            continuous=True,
            max_request_seconds=30,
        )
        self.assertEqual(app._limit_seconds(), 30)


class PravilaNadPasusima(unittest.TestCase):
    def test_prazan_red_prezivljava(self):
        app = napravi()
        out = app._rules_over_paragraphs("Prvi pasus, ovde.\n\nDrugi pasus!")
        self.assertEqual(out, "prvi pasus ovde\n\ndrugi pasus")

    def test_brojevi_ostaju_celi(self):
        app = napravi()
        self.assertEqual(app._rules_over_paragraphs("U 10:30, za 3,5 dinara."), "u 10:30 za 3,5 dinara")


if __name__ == "__main__":
    unittest.main()


class ZavrsnaObrada(unittest.TestCase):
    """Sta se primenjuje POSLE modela kad on sredjuje tekst."""

    def test_kvacice_se_skidaju_ako_je_trazeno(self):
        app = napravi(ascii_diacritics=True)
        self.assertEqual(app._after_model("Juče je bio čas."), "juce je bio cas")

    def test_interpunkcija_i_velika_slova_ostaju(self):
        # To je bas posao koji je model dobio — nasa pravila ga ne smeju gasiti.
        app = napravi(text_style="written")
        self.assertEqual(app._after_model("Juče je bio čas."), "Juče je bio čas.")

    def test_hiljade_se_spajaju(self):
        # Tacka hiljada nestaje, ali valuta recima zadrzava razmak: "5000dinara"
        # izgleda kao greska.
        app = napravi()
        self.assertEqual(app._after_model("Cena je 5.000 dinara."), "cena je 5000 dinara")


class StilPresudjuje(unittest.TestCase):
    """Ono sto je model usput sredio ne sme da preskoci izbor korisnika."""

    def test_izgovoreno_skida_interpunkciju_i_kad_je_model_sredio(self):
        # Prolaz u kome model slusa snimak vraca tekst sa tackama i upitnicima.
        # Ranije se tada preskakalo pravilo, pa je znak pitanja cas bio cas nije.
        app = napravi(text_style="spoken")
        self.assertEqual(
            app._rules_over_paragraphs("Da li si tu? Nisam siguran."),
            "da li si tu nisam siguran",
        )

    def test_sredjeno_zadrzava_interpunkciju(self):
        app = napravi(text_style="written")
        # Stil "sredjeno" ne dira ni znake ni velika slova.
        self.assertEqual(app._after_model("Da li si tu?"), "Da li si tu?")

    def test_sredjeno_i_dalje_skracuje(self):
        # Skracenice rade nezavisno od stila; malo slovo dolazi iz same zamene.
        app = napravi(text_style="written")
        self.assertEqual(app._after_model("Ne znam, da li si tu?"), "nzm, da li si tu?")


class NacinUpisa(unittest.TestCase):
    """Clipboard se ne dira bez potrebe — hvataci istorije beleže svaku izmenu."""

    def test_obican_tekst_se_kuca(self):
        from dictate import insert
        self.assertTrue(insert.kuca_se("zdravo kako si", "auto"))

    def test_pasusi_idu_preko_clipboarda(self):
        # Kucanje bi nov red poslalo kao Enter — u ćaskanju to šalje poruku.
        from dictate import insert
        self.assertFalse(insert.kuca_se("prvi pasus\n\ndrugi", "auto"))

    def test_izricit_izbor_se_postuje(self):
        from dictate import insert
        self.assertTrue(insert.kuca_se("bilo\nsta", "type"))
        self.assertFalse(insert.kuca_se("bez novog reda", "paste"))


class ZavrsniRazmak(unittest.TestCase):
    """Razmak putuje sa tekstom, nikad sam."""

    def komadi(self, tekst, velicina=4):
        from dictate import insert
        return insert.komadi(tekst, velicina)

    def test_komad_koji_je_sam_razmak_se_spaja(self):
        # "abcd" + " " bi inace bio poseban dogadjaj koji aplikacija odbaci.
        self.assertEqual(self.komadi("abcd "), ["abcd "])

    def test_ceo_tekst_se_prenosi(self):
        for tekst in ("zdravo kako si ", "a", "", "ab cd ef gh ij "):
            self.assertEqual("".join(self.komadi(tekst)), tekst)

    def test_razmak_unutar_teksta_ne_dira_podelu(self):
        self.assertEqual(self.komadi("ab cd"), ["ab c", "d"])

    def test_sam_razmak_ostaje_jedini_komad(self):
        self.assertEqual(self.komadi(" "), [" "])


class SpisakTacaka(unittest.TestCase):
    """Naša pravila su spisak spajala u jedan red i jela crtice."""

    def test_svaka_tacka_ostaje_u_svom_redu(self):
        app = napravi(text_style="spoken")
        spisak = "- Da li postoji mogućnost?\n- Ta opcija se selektuje.\n- Tekst je bez oznaka."
        out = app._rules_over_paragraphs(spisak)
        self.assertEqual(len(out.splitlines()), 3)
        self.assertTrue(all(r.startswith("- ") for r in out.splitlines()))

    def test_prazan_red_izmedju_pasusa_prezivljava(self):
        app = napravi(text_style="spoken")
        out = app._rules_over_paragraphs("prvi pasus.\n\ndrugi pasus.")
        self.assertEqual(out, "prvi pasus\n\ndrugi pasus")

    def test_crtica_usred_reda_odlazi(self):
        # Kada je uklanjanje interpunkcije ukljuceno, odlazi i crtica u reci.
        app = napravi(text_style="spoken")
        self.assertEqual(app._rules_over_paragraphs("crno-beli film - lep"), "crno-beli film lep")

    def test_mala_slova_i_interpunkcija_su_nezavisni(self):
        app = napravi(lowercase=False, strip_punctuation=True)
        self.assertEqual(app._apply_rules("Zdravo, SVETE!"), "Zdravo SVETE")
        app = napravi(lowercase=True, strip_punctuation=False)
        self.assertEqual(app._apply_rules("Zdravo, SVETE!"), "zdravo, svete!")


class BojaNaslova(unittest.TestCase):
    """U naslovu su uvek cifre; stanje se čita iz boje."""

    def napravi_sat(self, **kw):
        import time
        app = napravi(**kw)
        app._polishing = False
        app._pending = 0
        app._record_started_at = time.monotonic()
        return app

    def test_model_ima_prednost(self):
        app = self.napravi_sat()
        app._polishing = True
        app._pending = 3
        self.assertEqual(app._title_color(), "polishing")

    def test_prepoznavanje_je_narandzasto(self):
        app = self.napravi_sat()
        app._pending = 1
        self.assertEqual(app._title_color(), "busy")

    def test_neprekidno_nema_crvenu_granicu(self):
        # Bez granice od 30s crveno upozorenje nema šta da najavi.
        app = self.napravi_sat(continuous=True)
        app._record_started_at = 0.0
        self.assertIsNone(app._title_color())

    def test_blizu_granice_je_crveno(self):
        app = self.napravi_sat(continuous=False)
        app._record_started_at = 0.0      # kao da traje jako dugo
        self.assertEqual(app._title_color(), "recording")


class StopDokSePokrece(unittest.TestCase):
    """Brz start pa odmah stop.

    Pokretanje ceka na oslobodjen mikrofon, pa STOP ume da stigne dok
    `_recorder` jos ne postoji. Bez pamcenja tog STOP-a snimanje krene posle
    njega i vise ne staje — taster tada deluje mrtvo.
    """

    def napravi(self):
        app = app_mod.DictateApp.__new__(app_mod.DictateApp)
        app._session_lock = threading.Lock()
        app._recorder = None
        app._starting = 0
        app._stop_requested = False
        return app

    def test_stop_bez_pokretanja_ne_dize_zastavicu(self):
        app = self.napravi()
        app._on_stop()
        self.assertFalse(app._stop_requested)

    def test_stop_dok_se_pokrece_pamti_se(self):
        app = self.napravi()
        app._starting = 1
        app._on_stop()
        self.assertTrue(app._stop_requested)

    def test_pokretanje_pokupi_zapamcen_stop(self):
        app = self.napravi()
        zaustavljeno = []

        def lazni_start():
            # Ovde `_on_start` stoji dok ceka mikrofon; STOP stigne bas tada.
            app._on_stop()
            self.assertTrue(app._stop_requested)
            with app._session_lock:
                propusteni = app._stop_requested
                app._stop_requested = False
            if propusteni:
                zaustavljeno.append(True)
            return True

        app._start_recording = lazni_start
        self.assertTrue(app._on_start())
        self.assertEqual(zaustavljeno, [True])
        self.assertEqual(app._starting, 0)
        self.assertFalse(app._stop_requested)

    def test_brojac_se_vrati_i_kad_pokretanje_pukne(self):
        def puca():
            raise RuntimeError("mikrofon")

        app = self.napravi()
        app._start_recording = puca
        with self.assertRaises(RuntimeError):
            app._on_start()
        self.assertEqual(app._starting, 0)


class JedanZahtevPoDiktatu(unittest.TestCase):
    """Koji put uzima koji izvor.

    Gemini Live strimuje zvuk DOK snimanje traje (`_transcribe_live`) — tako
    nema cekanja na kraju: izmereno 15.6s naspram 0.0s na 64.7s zvuka. OpenAI
    salje ceo snimak posle Stop-a. Google sece na pauzama i lepi tekst usput.
    """

    def napravi(self, izvor):
        app = app_mod.DictateApp.__new__(app_mod.DictateApp)
        app.cfg = {
            "transcription_provider": izvor, "continuous": True,
            "sample_rate": 16000, "pause_seconds": 0.7,
            "segment_after_seconds": 0, "max_request_seconds": 30,
        }
        app._dump = None
        app._debug_sessions = {}
        return app

    def put(self, izvor):
        """Koji se put bira, bez pravog snimanja."""
        app = self.napravi(izvor)
        izabrano = []
        app._transcribe_whole = lambda rec, oznaka="ceo": izabrano.append(oznaka)
        app._transcribe_live = lambda rec: izabrano.append("gemini_live")
        app._segmenting = lambda: bool(app.cfg.get("continuous"))

        class Snimak:
            session = 1
            cancelled = True

        app._tracked = lambda rec: iter(())
        app._settle_phase = lambda *a, **k: None
        app._recognize_or_keep = lambda pcm: ""
        app._keep_audio = lambda *a: None
        app._transcribe(Snimak())
        return izabrano

    def test_live_strimuje_u_toku(self):
        self.assertEqual(self.put("gemini_live"), ["gemini_live"])

    def test_openai_ostaje_na_svom_putu(self):
        self.assertEqual(self.put("openai"), ["openai"])

    def test_google_sece_na_pauzama(self):
        # Prazan spisak = nije uzet put "ceo diktat", nego uobicajeni.
        self.assertEqual(self.put("google"), [])
