"""Mikrofon se oslobadja kad snimanje stane, i kad mreza visi."""

import threading
import time
import unittest

from dictate import audio
from dictate.app import DictateApp


class _Snimac(audio.Recorder):
    """Recorder bez PortAudio-a: komade ubacuje test."""

    def __init__(self):
        super().__init__(max_seconds=60)
        self.snimak = None

    def ubaci(self, pcm: bytes):
        self._q.put(pcm)


class _Aplikacija:
    def __init__(self):
        self.oslobodjen = threading.Event()

    def _release_recorder(self, recorder):
        self.oslobodjen.set()


class Odvojen(unittest.TestCase):
    def test_stop_oslobadja_mikrofon_dok_slanje_visi(self):
        aplikacija = _Aplikacija()
        snimac = _Snimac()
        komadi = DictateApp._tracked(aplikacija, snimac)
        pusti_slanje = threading.Event()

        def salje():
            for _ in komadi:
                # Prvi komad, pa slanje stane kao zaglavljen Live strim.
                pusti_slanje.wait(5)

        nit = threading.Thread(target=salje, daemon=True)
        nit.start()
        snimac.ubaci(b"\x00\x00" * 1600)
        time.sleep(0.1)
        snimac.ubaci(b"\x00\x00" * 1600)
        pocetak = time.monotonic()
        snimac.stop()
        self.assertTrue(aplikacija.oslobodjen.wait(1.0),
                        "mikrofon je ostao zauzet dok slanje visi")
        self.assertLess(time.monotonic() - pocetak, 1.0)
        pusti_slanje.set()
        nit.join(2)
        self.assertFalse(nit.is_alive())


if __name__ == "__main__":
    unittest.main()


class Osigurac(unittest.TestCase):
    """STOP zaustavlja sat i kad se snimac zaglavi iza njega."""

    def _app(self, snimac):
        app = DictateApp.__new__(DictateApp)
        app._session_lock = threading.Lock()
        app._recorder = snimac
        app.oslobodjen = threading.Event()
        app._release_recorder = lambda rec: app.oslobodjen.set()
        app._settle_phase = lambda *a, **k: None
        return app

    def test_zaglavljen_snimac_se_oslobadja(self):
        snimac = _Snimac()
        app = self._app(snimac)
        app._cuvar_zaustavljanja(snimac)
        self.assertIsNone(app._recorder)
        self.assertTrue(app.oslobodjen.wait(1.0))

    def test_uredno_zaustavljen_ne_dira_nista(self):
        snimac = _Snimac()
        snimac.released = True
        app = self._app(snimac)
        app._cuvar_zaustavljanja(snimac)
        self.assertIs(app._recorder, snimac)
        self.assertFalse(app.oslobodjen.is_set())

    def test_nov_diktat_se_ne_prekida(self):
        stari, novi = _Snimac(), _Snimac()
        app = self._app(novi)
        app._cuvar_zaustavljanja(stari)
        self.assertIs(app._recorder, novi)
