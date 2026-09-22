"""Azuriranje Mac aplikacije iz GitHub izdanja, bez mreze."""

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dictate import azuriranje


def _arhiva(fajlovi: dict[str, str]) -> bytes:
    """Arhiva u obliku koji vraca GitHub: jedan koreni folder."""
    bafer = io.BytesIO()
    with tarfile.open(fileobj=bafer, mode="w:gz") as tar:
        for ime, sadrzaj in fajlovi.items():
            podaci = sadrzaj.encode("utf-8")
            info = tarfile.TarInfo(f"milev051-diktat-abc123/{ime}")
            info.size = len(podaci)
            tar.addfile(info, io.BytesIO(podaci))
    return bafer.getvalue()


class _Odgovor(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Verzije(unittest.TestCase):
    def test_poredi_broj_po_broj(self):
        self.assertTrue(azuriranje.novije("v1.9", "v1.11"))
        self.assertFalse(azuriranje.novije("v1.11", "v1.9"))

    def test_ista_verzija_nije_novija(self):
        self.assertFalse(azuriranje.novije("v1.66", "v1.66"))
        self.assertFalse(azuriranje.novije("1.66", "v1.66.0"))

    def test_nepoznata_verzija_trazi_azuriranje(self):
        self.assertTrue(azuriranje.novije("", "v1.66"))


class Odgovor(unittest.TestCase):
    def test_cita_oznaku_i_arhivu(self):
        izdanje = azuriranje.iz_odgovora(json.dumps({
            "tag_name": "v1.67", "name": "Diktat 1.67",
            "tarball_url": "https://api.github.com/repos/milev051/diktat/tarball/v1.67",
        }))
        self.assertEqual(izdanje.oznaka, "v1.67")
        self.assertTrue(izdanje.arhiva.endswith("/tarball/v1.67"))

    def test_bez_oznake_je_greska(self):
        with self.assertRaises(ValueError):
            azuriranje.iz_odgovora(json.dumps({"tarball_url": "x"}))


class Instalacija(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dom = Path(self.tmp.name)
        self.app = self.dom / "app"
        (self.app / "dictate").mkdir(parents=True)
        (self.app / "dictate" / "stari.py").write_text("x = 1\n")
        (self.app / "run.py").write_text("stari\n")
        (self.app / "requirements.txt").write_text("rumps\n")
        (self.app / "config.json").write_text('{"polish_api_key": "moj"}\n')
        self.zakrpe = [
            mock.patch.object(azuriranje, "DOM", self.dom),
            mock.patch.object(azuriranje, "INSTALIRANO", self.app),
            mock.patch.object(azuriranje, "KOREN", self.app),
        ]
        for zakrpa in self.zakrpe:
            zakrpa.start()

    def tearDown(self):
        for zakrpa in self.zakrpe:
            zakrpa.stop()
        self.tmp.cleanup()

    def _instaliraj(self, fajlovi):
        izdanje = azuriranje.Izdanje("v1.67", "Diktat 1.67", "https://primer/tarball")
        with mock.patch.object(azuriranje, "_zahtev",
                               return_value=_Odgovor(_arhiva(fajlovi))):
            azuriranje.instaliraj(izdanje)

    def test_zameni_kod_a_zadrzi_podesavanja(self):
        self._instaliraj({
            "run.py": "novi\n",
            "dictate/novi.py": "y = 2\n",
            "requirements.txt": "rumps\n",
            "android/app/build.gradle.kts": "ne kopira se\n",
        })
        self.assertEqual((self.app / "run.py").read_text(), "novi\n")
        self.assertTrue((self.app / "dictate" / "novi.py").exists())
        self.assertFalse((self.app / "dictate" / "stari.py").exists())
        self.assertFalse((self.app / "android").exists())
        self.assertIn("moj", (self.app / "config.json").read_text())
        self.assertEqual(azuriranje.trenutna_verzija(), "v1.67")
        # Radni folder ne ostaje posle instalacije.
        self.assertEqual(sorted(p.name for p in self.dom.iterdir()), ["app"])

    def test_losa_arhiva_ne_dira_instalaciju(self):
        with self.assertRaises(ValueError):
            self._instaliraj({"README.md": "bez koda\n"})
        self.assertEqual((self.app / "run.py").read_text(), "stari\n")

    def test_razvojna_kopija_se_ne_azurira(self):
        with mock.patch.object(azuriranje, "KOREN", self.dom / "projekat"):
            with self.assertRaises(RuntimeError):
                self._instaliraj({"run.py": "novi\n", "dictate/a.py": ""})


if __name__ == "__main__":
    unittest.main()
