"""Tisina dok se snima: vraca se samo ono sto je Diktat promenio."""

import unittest
from unittest import mock

from dictate import zvuk


class Tisina(unittest.TestCase):
    def setUp(self):
        self.utisan = False
        self.pustaju = []
        self.pauze = 0
        zakrpe = [
            mock.patch.object(zvuk, "utisan", lambda: self.utisan),
            mock.patch.object(zvuk, "postavi_utisan", self._postavi),
            mock.patch.object(zvuk, "ko_pusta_zvuk", lambda: list(self.pustaju)),
            mock.patch.object(zvuk, "_taster_pauze", self._pauza),
            mock.patch.object(zvuk, "POSLE_PAUZE", 0),
        ]
        for z in zakrpe:
            z.start()
            self.addCleanup(z.stop)
        self.t = zvuk.Tisina()

    def _postavi(self, da):
        self.utisan = da

    def _pauza(self):
        self.pauze += 1

    def krug(self, **cfg):
        self.t.pocni(cfg)
        self.t._nit.submit(lambda: None).result()
        stanje = (self.utisan, self.pauze)
        self.t.vrati()
        self.t._nit.submit(lambda: None).result()
        return stanje

    def test_utisa_pa_vrati(self):
        self.assertEqual(self.krug(utisaj_zvuk=True), (True, 0))
        self.assertFalse(self.utisan)

    def test_vec_utisan_ostaje_utisan(self):
        self.utisan = True
        self.krug(utisaj_zvuk=True)
        self.assertTrue(self.utisan)

    def test_pauza_samo_kad_plejer_svira(self):
        self.pustaju = ["com.google.Chrome.helper"]
        self.assertEqual(self.krug(pauziraj_plejer=True), (False, 1))
        self.assertEqual(self.pauze, 2)   # pauza, pa nastavak

    def test_bez_zvuka_nema_tastera(self):
        # Taster je prekidac: bez ovoga bi pokrenuo Muziku.
        self.krug(pauziraj_plejer=True)
        self.assertEqual(self.pauze, 0)

    def test_poziv_nije_plejer(self):
        self.pustaju = ["us.zoom.xos", "net.whatsapp.WhatsApp"]
        self.krug(pauziraj_plejer=True)
        self.assertEqual(self.pauze, 0)

    def test_ugaseno_ne_dira_nista(self):
        self.utisan = False
        self.pustaju = ["com.spotify.client"]
        self.krug()
        self.assertEqual((self.utisan, self.pauze), (False, 0))

    def test_vracanje_bez_pocetka_ne_radi_nista(self):
        self.t.vrati_odmah()
        self.assertEqual((self.utisan, self.pauze), (False, 0))


if __name__ == "__main__":
    unittest.main()
