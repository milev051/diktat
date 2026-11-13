"""Osvežavanje istorije ne sme da ugasi mikrofon novog diktata."""

import unittest
from unittest.mock import patch

from dictate import audio


class Strim:
    def __init__(self, callback, daje_zvuk=True, **kwargs):
        self.callback = callback
        self.daje_zvuk = daje_zvuk
        self.active = False

    def start(self):
        self.active = True
        if self.daje_zvuk:
            self.callback(b"\x00\x00" * 1600, 1600, None, None)

    def stop(self):
        self.active = False

    def close(self):
        self.active = False


class ZivotniCiklus(unittest.TestCase):
    def test_brzi_novi_diktat_prezivi_osvezavanje_prethodne_istorije(self):
        with patch.object(audio.sd, "RawInputStream", side_effect=Strim), \
                patch.object(audio.sd, "_terminate") as terminate, \
                patch.object(audio.sd, "_initialize"):
            stari, novi = audio.Recorder(), audio.Recorder()
            try:
                stari.start()
                stari.stop()
                stari.close()
                novi.start()
                self.assertFalse(audio.refresh_devices())
                terminate.assert_not_called()
                self.assertTrue(novi._stream.active)
                pre = novi.captured
                novi._stream.callback(b"\x01\x00" * 1600, 1600, None, None)
                self.assertGreater(novi.captured, pre)
            finally:
                stari.close()
                novi.close()
            self.assertTrue(audio.refresh_devices())
            terminate.assert_called_once()

    def test_otvoren_mikrofon_bez_zvuka_se_ponovo_otvara(self):
        strimovi = []

        def napravi(**kw):
            strim = Strim(daje_zvuk=bool(strimovi), **kw)
            strimovi.append(strim)
            return strim

        with patch.object(audio.sd, "RawInputStream", side_effect=napravi), \
                patch.object(audio.sd, "_terminate"), \
                patch.object(audio.sd, "_initialize"), \
                patch.object(audio, "START_ROK", 0.001):
            snimac = audio.Recorder()
            try:
                snimac.start()
                self.assertEqual(len(strimovi), 2)
                self.assertFalse(strimovi[0].active)
                self.assertTrue(strimovi[1].active)
                self.assertGreater(snimac.captured, 0)
            finally:
                snimac.close()

    def test_neuspeo_mikrofon_se_ne_prijavljuje_kao_snima(self):
        with patch.object(audio.sd, "RawInputStream", side_effect=lambda **kw: Strim(daje_zvuk=False, **kw)), \
                patch.object(audio.sd, "_terminate"), \
                patch.object(audio.sd, "_initialize"), \
                patch.object(audio, "START_ROK", 0.001):
            snimac = audio.Recorder()
            with self.assertRaisesRegex(RuntimeError, "ne šalje zvuk"):
                snimac.start()
            self.assertIsNone(snimac._stream)
            self.assertNotIn(snimac, audio._active_recorders)
