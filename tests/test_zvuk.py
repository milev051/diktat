"""Tisina dok se snima: vraca se samo ono sto je Diktat promenio."""

import time
import unittest
from unittest import mock

from dictate import zvuk


class Tisina(unittest.TestCase):
    def setUp(self):
        self.utisan = False
        self.pustaju = []
        self.pauze = 0
        self.kartice = []           # Chrome kartice sa „Audio playing"
        self.chrome_svira = []      # sta JavaScript zatekne kako svira
        self.nastavljeno = []
        zakrpe = [
            mock.patch.object(zvuk, "utisan", lambda: self.utisan),
            mock.patch.object(zvuk, "postavi_utisan", self._postavi),
            mock.patch.object(zvuk, "ko_pusta_zvuk", lambda: list(self.pustaju)),
            mock.patch.object(zvuk, "_taster_pauze", self._pauza),
            mock.patch.object(zvuk, "zvucne_kartice", lambda: list(self.kartice)),
            mock.patch.object(zvuk, "chrome_pauziraj", self._chrome_pauziraj),
            mock.patch.object(zvuk, "chrome_nastavi", self.nastavljeno.extend),
            mock.patch.object(zvuk, "POSLE_PAUZE", 0),
            mock.patch.object(zvuk, "ODLOZENO_VRACANJE", 0.05),
        ]
        for z in zakrpe:
            z.start()
            self.addCleanup(z.stop)
        self.t = zvuk.Tisina()

    def _postavi(self, da):
        self.utisan = da

    def _pauza(self):
        self.pauze += 1

    def _chrome_pauziraj(self, kartice):
        return list(self.chrome_svira) if kartice else []

    def sacekaj(self, rok=0.0):
        time.sleep(rok)
        self.t._nit.submit(lambda: None).result()

    def krug(self, **cfg):
        self.t.pocni(cfg)
        self.sacekaj()
        stanje = (self.utisan, self.pauze)
        self.t.vrati()
        self.sacekaj(0.15)
        return stanje

    def test_utisa_pa_vrati(self):
        self.assertEqual(self.krug(utisaj_zvuk=True), (True, 0))
        self.assertFalse(self.utisan)

    def test_vec_utisan_ostaje_utisan(self):
        self.utisan = True
        self.krug(utisaj_zvuk=True)
        self.assertTrue(self.utisan)

    def test_samostalni_plejer_taster(self):
        self.pustaju = ["com.spotify.client"]
        self.assertEqual(self.krug(pauziraj_plejer=True), (False, 1))
        self.assertEqual(self.pauze, 2)   # pauza, pa nastavak

    def test_chrome_bez_tastera_nastavlja_samo_pauzirano(self):
        self.pustaju = ["com.google.Chrome.helper"]
        self.kartice = ["Video - YouTube - Audio playing"]
        self.chrome_svira = ["11:22"]
        self.krug(pauziraj_plejer=True)
        self.assertEqual(self.pauze, 0)
        self.assertEqual(self.nastavljeno, ["11:22"])

    def test_pauziran_video_u_chrome_se_ne_pokrece(self):
        # Pauziran neposredno pred diktat: Chrome jos ~2 s drzi i izlaz i
        # oznaku „Audio playing". Taster bi ga tada POKRENUO (27.09.2026);
        # JavaScript ga zatekne pauziranog i ne dira.
        self.pustaju = ["com.google.Chrome.helper"]
        self.kartice = ["Video - YouTube - Audio playing"]
        self.chrome_svira = []
        self.krug(pauziraj_plejer=True)
        self.assertEqual((self.pauze, self.nastavljeno), (0, []))

    def test_chrome_greska_ne_obara_utisavanje(self):
        self.pustaju = ["com.google.Chrome.helper"]
        self.kartice = ["Video - Audio playing"]
        with mock.patch.object(zvuk, "chrome_pauziraj",
                               side_effect=RuntimeError("JavaScript iskljucen")):
            self.t.pocni({"pauziraj_plejer": True, "utisaj_zvuk": True})
            self.sacekaj()
        self.assertTrue(self.utisan)

    def test_safari_se_ne_pauzira(self):
        self.pustaju = ["com.apple.WebKit.GPU"]
        self.krug(pauziraj_plejer=True)
        self.assertEqual((self.pauze, self.nastavljeno), (0, []))

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

    def test_brzi_niz_diktata_ne_pusta_izmedju(self):
        # Stop pa odmah start: vracanje je odlozeno, pa ga novi diktat
        # ponisti. Ranije se video cuo izmedju svaka dva snimka.
        self.pustaju = ["com.spotify.client"]
        cfg = {"pauziraj_plejer": True, "utisaj_zvuk": True}
        for _ in range(3):
            self.t.pocni(cfg)
            self.sacekaj()
            self.t.vrati()
            self.sacekaj(0.01)
            self.assertTrue(self.utisan)
            self.assertEqual(self.pauze, 1)
        self.sacekaj(0.15)
        self.assertEqual((self.utisan, self.pauze), (False, 2))

    def test_vracanje_bez_pocetka_ne_radi_nista(self):
        self.t.vrati_odmah()
        self.assertEqual((self.utisan, self.pauze), (False, 0))


class ImenaZaAppleScript(unittest.TestCase):
    def test_navodnici_u_naslovu(self):
        self.assertEqual(zvuk._as_tekst('a "b" c\\d'), '"a \\"b\\" c\\\\d"')


if __name__ == "__main__":
    unittest.main()
