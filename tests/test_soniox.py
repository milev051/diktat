"""Soniox tok bez mreže: lažni WebSocket vraća tokene kao pravi server."""

import json
import unittest

from dictate import config, sonioxstt


class LazniWS:
    def __init__(self, url, timeout=30.0):
        self.poslato = []
        self.odgovori = []
        self.close_code = None
        self.close_reason = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def set_read_poll_timeout(self, s):
        pass

    def send_json(self, poruka):
        self.poslato.append(("json", poruka))

    def send_bytes(self, data):
        self.poslato.append(("bin", data))

    def send_text(self, tekst):
        self.poslato.append(("text", tekst))
        # Kraj zvuka: server šalje konačne tokene i finished.
        self.odgovori += [
            {"tokens": [{"text": "Dobar", "is_final": True},
                        {"text": " dan", "is_final": False}]},
            {"tokens": [{"text": " dan", "is_final": True},
                        {"text": "<fin>", "is_final": True}], "finished": True},
        ]

    def wait_readable(self, s):
        return bool(self.odgovori)

    def recv_json(self):
        return self.odgovori.pop(0) if self.odgovori else None


class SonioxTest(unittest.TestCase):
    def test_stream_vraca_konacne_tokene_bez_kontrolnih(self):
        napravljeni = []

        def fabrika(url, timeout):
            ws = LazniWS(url, timeout)
            napravljeni.append(ws)
            return ws

        cfg = {"soniox_api_key": "x", "sample_rate": 16000}
        prikazi = []
        tekst = sonioxstt.recognize_live_stream(
            [b"\x00\x01" * 10, b"", b"\x00\x01" * 10], cfg,
            on_update=prikazi.append, _ws_factory=fabrika)
        self.assertEqual(tekst, "Dobar dan")
        ws = napravljeni[0]
        prvo = ws.poslato[0][1]
        self.assertEqual(prvo["model"], "stt-rt-v6")
        self.assertEqual(prvo["language_hints"], ["sr"])
        self.assertEqual([v for v, _ in ws.poslato], ["json", "bin", "bin", "text"])
        self.assertIn("Dobar dan", prikazi)

    def test_bez_kljuca_jasna_greska(self):
        stari = sonioxstt.KEY_FILE
        sonioxstt.KEY_FILE = sonioxstt.Path("/nepostojeci/kljuc")
        try:
            with self.assertRaises(sonioxstt.SonioxError):
                sonioxstt.key({})
        finally:
            sonioxstt.KEY_FILE = stari

    def test_greska_servera(self):
        class Los(LazniWS):
            def send_json(self, poruka):
                self.odgovori.append({"error_code": 401, "error_message": "Invalid API key"})

        with self.assertRaises(sonioxstt.SonioxError) as ctx:
            sonioxstt.recognize_live_stream(
                [b"\x00\x00"], {"soniox_api_key": "x"}, _ws_factory=Los)
        self.assertFalse(ctx.exception.retryable)

    def test_politika_cuva_soniox(self):
        cfg = config.desktop_policy({"compact_desktop_v1": True,
                                     "transcription_provider": "soniox"})
        self.assertEqual(cfg["transcription_provider"], "soniox")
        self.assertIn("soniox", config.PROVIDERS)


if __name__ == "__main__":
    unittest.main()
