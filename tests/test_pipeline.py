"""Tok diktata: sesije, kada se ceka kraj, pravila nad tekstom.

Aplikacija se pravi preko `__new__` da se ne pokrece rumps petlja — ovde se
proverava sama logika, bez ekrana i bez mikrofona.
"""

import threading
import queue
import time
import unittest

from dictate import app as app_mod
from dictate import insert


def napravi(**kw):
    app = app_mod.DictateApp.__new__(app_mod.DictateApp)
    app.cfg = {
        "sample_rate": 16000, "polish_api_key": "x", "polish_paragraphs": False,
        "text_style": "spoken", "join_thousands": True,
        "lowercase": True, "strip_punctuation": True,
    }
    app.cfg.update(kw)
    if "lowercase" not in kw:
        app.cfg["lowercase"] = app.cfg["text_style"] != "written"
    if "strip_punctuation" not in kw:
        app.cfg["strip_punctuation"] = app.cfg["text_style"] != "written"
    app._formal_lock = threading.Lock()
    app._formal_parts = {}
    app._count_lock = threading.Lock()
    app._pending_by = {}
    app._session_seq = 0
    return app


class DvaDiktataOdjednom(unittest.TestCase):
    """Nov diktat sme da pocne dok se prethodni obradjuje."""

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


class DirektanGeminiUnos(unittest.TestCase):
    def test_potvrdjeni_delovi_idu_odmah_i_ne_dupliraju_se_na_kraju(self):
        app = napravi(polish_paragraphs=False)
        app._insert_q = queue.Queue()
        app._pending = 2
        app._pending_by = {1: 1, 2: 1}
        app._maybe_polish = lambda: None
        app._settle_phase = lambda: None
        app._remember = lambda _: None
        written = []
        old_live, old_insert = insert.insert_live, insert.insert
        insert.insert_live = lambda text: written.append(text)
        insert.insert = lambda text, **kw: written.append(text)
        try:
            threading.Thread(target=app._insert_worker, daemon=True).start()
            app._deliver_live_part(2, "drugi ", 2)
            time.sleep(0.02)
            self.assertEqual(written, [])
            app._deliver(1, "prvi ", 1)
            deadline = time.monotonic() + 1
            while len(written) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(written, ["prvi ", "drugi "])
            app._deliver(2, "", 2)
            time.sleep(0.02)
            self.assertEqual(written, ["prvi ", "drugi "])
            self.assertEqual(app._pending, 0)
        finally:
            insert.insert_live, insert.insert = old_live, old_insert


class KadaSeCekaKraj(unittest.TestCase):
    def test_openai_bez_alata_ne_ceka(self):
        app = napravi(transcription_provider="openai")
        self.assertFalse(app._deferred())

    def test_bez_provere_i_bez_alata_tekst_ide_odmah(self):
        app = napravi()
        self.assertFalse(app._deferred())

    def test_izabran_alat_sam_po_sebi_pali_ai(self):
        # Glavnog prekidaca nema: izabran alat znaci da se AI koristi.
        app = napravi(polish_paragraphs=True)
        self.assertTrue(app._deferred())

    def test_bez_kljuca_nema_ai_ja_ma_sta_bilo_izabrano(self):
        app = napravi(polish_paragraphs=True, polish_api_key="")
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
        app._transcribe(Snimak())
        return izabrano

    def test_live_strimuje_u_toku(self):
        self.assertEqual(self.put("gemini_live"), ["gemini_live"])

    def test_openai_ostaje_na_svom_putu(self):
        self.assertEqual(self.put("openai"), ["openai"])

    def test_google_sece_na_pauzama(self):
        # Prazan spisak = nije uzet put "ceo diktat", nego uobicajeni.
        self.assertEqual(self.put("google"), [])


class GranicaTrajanja(unittest.TestCase):
    """Koliko sme da traje jedan pritisak, po izvoru transkripcije."""

    def limit(self, **izmene):
        return napravi(polish_api_key="x", **izmene)._limit_seconds()

    def test_gemini_live_staje_posle_dva_minuta(self):
        # Jedini izvor koji salje zvuk DOK snimas (~2,5 MB/min): zaboravljen
        # mikrofon tu curi podatke sve vreme, a ne tek na kraju.
        self.assertEqual(self.limit(transcription_provider="gemini_live"), 120.0)

    def test_granica_za_live_ne_zavisi_od_neprekidnog(self):
        # Ne stiti od predugackog ZAHTEVA nego od zaboravljenog mikrofona.
        self.assertEqual(
            self.limit(transcription_provider="gemini_live", continuous=False), 120.0
        )

    def test_ostali_izvori_zadrzavaju_svoje_granice(self):
        self.assertEqual(self.limit(transcription_provider="google"), 3600.0)
        self.assertEqual(
            self.limit(transcription_provider="google", continuous=False), 30.0
        )

    def test_neispravna_vrednost_pada_na_dva_minuta(self):
        self.assertEqual(
            self.limit(transcription_provider="gemini_live",
                       gemini_live_max_seconds="nije broj"), 120.0
        )

    def test_vrednost_se_drzi_u_granicama(self):
        for uneto, ocekivano in ((5, 30.0), (99999, 3600.0), (300, 300.0)):
            self.assertEqual(
                self.limit(transcription_provider="gemini_live",
                           gemini_live_max_seconds=uneto), ocekivano, uneto
            )


class PrikazUzivo(unittest.TestCase):
    """Okvir sa prepisom dok govoriš; u polje ide samo potvrđena celina."""

    class _Recorder:
        cancelled = False
        session = 1
        ticket = 1
        live_insert = False
        released = False

    def test_medjurezultat_ide_samo_u_okvir(self):
        app = napravi(live_preview=True)
        app._live_text = ""
        app._live_text_dirty = False
        app._live_preview(self._Recorder(), "ovo je MEĐUrezultat")
        # Prikaz prolazi kroz ista pravila kao i prepis koji se ubacuje
        # (ovde: mala slova; kvačice se skidaju samo ako je to izabrano).
        self.assertEqual(app._live_text, "ovo je međurezultat")
        self.assertTrue(app._live_text_dirty)

    def test_otkazan_diktat_ne_crta(self):
        app = napravi(live_preview=True)
        app._live_text = ""
        app._live_text_dirty = False
        recorder = self._Recorder()
        recorder.cancelled = True
        app._live_preview(recorder, "ovo se ne prikazuje")
        self.assertEqual(app._live_text, "")
        self.assertFalse(app._live_text_dirty)

    def test_prekidac_gasi_prikaz(self):
        self.assertTrue(napravi(live_preview=True)._live_preview_on())
        self.assertFalse(napravi(live_preview=False)._live_preview_on())


class GasenjePrikaza(unittest.TestCase):
    """Okvir nestaje u trenutku zaustavljanja, ne kad rep istekne."""

    class _Panel:
        def __init__(self):
            self.visible = False
            self.text = ""

        def show(self, text=""):
            self.visible = True
            self.text = text

        def set_text(self, text):
            self.text = text

        def hide(self):
            self.visible = False

    def _app(self):
        app = napravi(live_preview=True, transcription_provider="gemini_live")
        app.live_panel = self._Panel()
        app._live_text = "prva celina"
        app._live_text_dirty = True
        app._live_off = False
        app._recorder = object()
        app._starting = 0
        return app

    def test_crta_dok_snima(self):
        app = self._app()
        app._tick_live_panel()
        self.assertTrue(app.live_panel.visible)
        self.assertEqual(app.live_panel.text, "prva celina")

    def test_okvir_izlazi_pre_prvog_teksta(self):
        # Server ume celoj sesiji da ne posalje medjurezultat; okvir ipak mora
        # da izadje odmah, a ne tek uz potvrdjenu celinu na pauzi.
        app = self._app()
        app._live_text = ""
        app._live_text_dirty = False
        app._tick_live_panel()
        self.assertTrue(app.live_panel.visible)

    def test_bez_live_izvora_nema_okvira(self):
        app = self._app()
        app.cfg["transcription_provider"] = "google"
        app._tick_live_panel()
        self.assertFalse(app.live_panel.visible)

    def test_zaustavljanje_gasi_odmah(self):
        app = self._app()
        app._tick_live_panel()
        # Mikrofon jos drzi rep (recorder postoji), ali je STOP vec pritisnut.
        app._live_off = True
        app._tick_live_panel()
        self.assertFalse(app.live_panel.visible)

    def test_celina_posle_stopa_ne_vraca_okvir(self):
        app = self._app()
        app._tick_live_panel()
        app._live_off = True
        app._tick_live_panel()
        # Reader jos radi i salje poslednju potvrdjenu celinu.
        app._live_text = "poslednja celina"
        app._live_text_dirty = True
        app._tick_live_panel()
        self.assertFalse(app.live_panel.visible)
