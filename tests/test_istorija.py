"""Prikazani tekst preživi Stop, grešku mreže, neuspeo upis i pad procesa."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dictate.istorija import Arhiva
from dictate.upis import RedUpisa
from dictate.app import DictateApp


class TrajnaIstorija(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def red(self, **kwargs):
        return RedUpisa(lambda t: None, lambda t: None, lambda: False,
                        lambda s, t: None, lambda: None,
                        arhiva=Arhiva(self.folder), **kwargs)

    def test_prepis_iste_sesije_se_azurira_a_sve_verzije_ostaju(self):
        red = self.red()
        red.zapamti("prva reč", sesija=1)
        red.zapamti("prva reč i nastavak", sesija=1)
        self.assertEqual(red.istorija(), ["prva reč i nastavak"])
        self.assertEqual(self.red().istorija(), red.istorija())
        records = [json.loads(line) for line in next(self.folder.glob("*.jsonl")).read_text().splitlines() if line]
        self.assertEqual([x["text"] for x in records], ["prva reč", "prva reč i nastavak"])

    def test_ostecena_istorija_i_prekinuta_poslednja_linija_ne_gube_tekst(self):
        red = self.red()
        red.zapamti("sačuvan prepis", sesija=1)
        (self.folder / "istorija.json").write_text("oštećen fajl")
        with next(self.folder.glob("*.jsonl")).open("a") as handle:
            handle.write('{"text":')
        self.assertEqual(self.red().istorija(), ["sačuvan prepis"])
        recovered = self.red()
        recovered.zapamti("novi prepis", sesija=1)
        self.assertEqual(self.red().istorija(), ["novi prepis", "sačuvan prepis"])

    def test_neuspeo_glavni_upis_ima_nezavisnu_kopiju(self):
        (self.folder / "istorija.json").mkdir()
        red = self.red()
        self.assertTrue(red.zapamti("rezerva", sesija=1))
        self.assertEqual(self.red().istorija(), ["rezerva"])

    def test_neuspeo_disk_zadrzava_tekst_u_memoriji_i_prijavi_neuspeh(self):
        blocked = self.folder / "blocked"
        blocked.write_text("")
        red = RedUpisa(lambda t: None, lambda t: None, lambda: False,
                       lambda s, t: None, lambda: None, arhiva=Arhiva(blocked))
        self.assertFalse(red.zapamti("tekst u memoriji", sesija=1))
        self.assertEqual(red.istorija(), ["tekst u memoriji"])

    def test_sesije_posle_restarata_se_ne_prepisuju(self):
        self.red().zapamti("pre restarta", sesija=1)
        self.red().zapamti("posle restarta", sesija=1)
        self.assertEqual(self.red().istorija(), ["posle restarta", "pre restarta"])

    def test_stop_ne_ceka_mrezu_niti_tiket_prethodnog_diktata(self):
        clipboard = []
        red = self.red(clipboard=clipboard.append)
        red.novi_tiket(1)  # Prethodni diktat nikad ne vraća rezultat.
        ticket = red.novi_tiket(2)
        rec = SimpleNamespace(session=2, ticket=ticket, cancelled=False,
                              zaustavljen=False, live_insert=False,
                              _release_lock=threading.Lock(), live_text="diktat od dva minuta")
        app = DictateApp.__new__(DictateApp)
        app.upis, app._recorder = red, rec
        app._session_lock = threading.Lock()
        app._starting = 0
        app._live_off = False
        app._live_text = rec.live_text
        app.cfg = {"tail_seconds": 0.8}
        app.state = Mock()

        def stop(**kwargs):
            self.assertEqual(red.istorija(), [rec.live_text])
            self.assertEqual(clipboard, [])
            self.assertEqual(self.red().istorija(), [rec.live_text])

        rec.stop = stop
        with patch("dictate.snimanje.threading.Timer"):
            app._on_stop()
        self.assertTrue(app._live_off)
        self.assertEqual(red.na_cekanju(), 2)

    def test_tekst_je_sacuvan_pre_crtanja_novog_prikaza(self):
        app = DictateApp.__new__(DictateApp)
        app.upis = self.red()
        app.cfg = {"text_style": "written", "lowercase": False, "strip_punctuation": False}
        app._recorder = SimpleNamespace(session=1, cancelled=False, zaustavljen=False)
        app._live_text = "stari prikaz"
        save = app.upis.zapamti

        def checkpoint(text, **kwargs):
            self.assertEqual(app._live_text, "stari prikaz")
            return save(text, **kwargs)

        with patch.object(app.upis, "zapamti", side_effect=checkpoint):
            app._live_preview(app._recorder, "novi prikaz")
        self.assertEqual(self.red().istorija(), ["novi prikaz"])
        self.assertEqual(app._live_text, "novi prikaz")

    def test_greska_posle_stopa_ne_gubi_prikaz_i_ne_brise_novu_sesiju(self):
        clipboard = []
        red = self.red(clipboard=clipboard.append)
        app = DictateApp.__new__(DictateApp)
        old = SimpleNamespace(session=1, ticket=red.novi_tiket(1), captured=32000,
                              cancelled=False, snimak=None, live_text="stari ceo diktat",
                              prikaz_u_polju="stari ceo diktat")
        app.upis = red
        app._recorder = SimpleNamespace(session=2)
        app._live_text = "novi diktat na ekranu"
        app._prikaz_u_polju = "novi diktat u polju"
        app.cfg = {"sample_rate": 16000}
        app._transcribe = Mock(side_effect=RuntimeError("prekinuta veza"))
        app._release_recorder = Mock()
        app._add_recorded_seconds = Mock()
        app._settle_phase = Mock()
        app.state = Mock()
        with patch("dictate.snimanje.traceback.print_exc"):
            app._run_session(old)
        self.assertEqual(red.istorija(), ["stari ceo diktat"])
        self.assertEqual(self.red().istorija(), red.istorija())
        self.assertEqual(clipboard, [])
        self.assertEqual(app._live_text, "novi diktat na ekranu")
        self.assertEqual(app._prikaz_u_polju, "novi diktat u polju")

    def test_kasniji_upis_repa_cuva_ceo_tekst_bez_clipboarda(self):
        clipboard, done = [], threading.Event()
        red = self.red(clipboard=clipboard.append)
        red._posle = done.set
        ticket = red.novi_tiket(1)
        red.zapamti("ceo tekst sa nastavkom", sesija=1)
        red.pokreni()
        red.predaj(ticket, "sa nastavkom ", 1)
        self.assertTrue(done.wait(1))
        self.assertEqual(red.istorija(), ["ceo tekst sa nastavkom"])
        self.assertEqual(clipboard, [])

    def test_ukljucen_clipboard_cuva_ceo_diktat_posle_upisa_repa(self):
        clipboard, done = [], threading.Event()
        red = self.red(clipboard=clipboard.append, cuvaj_clipboard=lambda: True)
        red._posle = done.set
        ticket = red.novi_tiket(1)
        red.zapamti("ceo tekst sa nastavkom", sesija=1)
        red.pokreni()
        red.predaj(ticket, "sa nastavkom ", 1)
        self.assertTrue(done.wait(1))
        self.assertEqual(clipboard, ["ceo tekst sa nastavkom"])
        self.assertEqual(self.red().istorija(), ["ceo tekst sa nastavkom"])

    def test_zavrsetak_stare_sesije_ne_prepisuje_noviji_diktat_u_clipboardu(self):
        clipboard, done = [], threading.Event()
        red = self.red(clipboard=clipboard.append, cuvaj_clipboard=lambda: True)
        red._posle = done.set
        ticket = red.novi_tiket(1)
        red.zapamti("prvi ceo diktat", sesija=1)
        red.zapamti("drugi ceo diktat", sesija=2)
        red.pokreni()
        red.predaj(ticket, "rep prvog ", 1)
        self.assertTrue(done.wait(1))
        self.assertEqual(clipboard, ["drugi ceo diktat"])
