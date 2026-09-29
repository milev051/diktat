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


class Bundle(unittest.TestCase):
    def test_instalirana_aplikacija(self):
        self.assertEqual(
            azuriranje.bundle_iz_komande(
                "/bin/bash /Applications/Diktat.app/Contents/Resources/diktat.sh\n"),
            "/Applications/Diktat.app")

    def test_putanja_sa_razmakom(self):
        self.assertEqual(
            azuriranje.bundle_iz_komande(
                "/bin/bash /Users/x/Android apps/Diktat.app/Contents/MacOS/Diktat"),
            "/Users/x/Android apps/Diktat.app")

    def test_nepoznat_roditelj(self):
        self.assertEqual(azuriranje.bundle_iz_komande("-zsh"), "/Applications/Diktat.app")


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

    def test_instalacija_bez_zapisanog_foldera_ne_dira_nijedan_klon(self):
        # DOM je privremen i nema fajl `izvor`, pa se pravi projekat ne dira.
        self._instaliraj({"run.py": "novi\n", "dictate/a.py": ""})
        self.assertIn("nepoznat", azuriranje.azuriraj_izvor())

    def test_razvojna_kopija_se_ne_azurira(self):
        with mock.patch.object(azuriranje, "KOREN", self.dom / "projekat"):
            with self.assertRaises(RuntimeError):
                self._instaliraj({"run.py": "novi\n", "dictate/a.py": ""})


class OsvezavanjeFolderaProjekta(unittest.TestCase):
    """Posle azuriranja aplikacije i klon dobija novu verziju, ali bezbedno."""

    def setUp(self):
        import subprocess
        import tempfile
        from pathlib import Path
        self.koren = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.koren, True)

        def git(folder, *args):
            subprocess.run(["git", "-C", str(folder), *args], check=True,
                           capture_output=True)
        self.git = git
        # Ime puta nosi „milev051/diktat", kao prava adresa repozitorijuma.
        self.origin = self.koren / "milev051" / "diktat.git"
        self.origin.mkdir(parents=True)
        git(self.origin, "init", "-q", "--bare", "-b", "main")
        self.autor = self.koren / "autor"
        git(self.koren, "clone", "-q", str(self.origin), str(self.autor))
        for folder in (self.autor,):
            git(folder, "config", "user.email", "t@t")
            git(folder, "config", "user.name", "t")
        (self.autor / "requirements.txt").write_text("a\n")
        git(self.autor, "add", "-A")
        git(self.autor, "commit", "-q", "-m", "prvi")
        git(self.autor, "push", "-q", "origin", "main")
        self.klon = self.koren / "klon"
        git(self.koren, "clone", "-q", str(self.origin), str(self.klon))

    def nova_verzija(self):
        (self.autor / "novo.txt").write_text("x\n")
        self.git(self.autor, "add", "-A")
        self.git(self.autor, "commit", "-q", "-m", "drugi")
        self.git(self.autor, "push", "-q", "origin", "main")

    def test_cist_klon_se_osvezi(self):
        self.nova_verzija()
        ishod = azuriranje.azuriraj_izvor(folder=self.klon)
        self.assertIn("osvezen", ishod)
        self.assertTrue((self.klon / "novo.txt").exists())

    def test_neuvedene_izmene_ostaju_netaknute(self):
        self.nova_verzija()
        (self.klon / "requirements.txt").write_text("moje\n")
        ishod = azuriranje.azuriraj_izvor(folder=self.klon)
        self.assertIn("neuvedene izmene", ishod)
        self.assertFalse((self.klon / "novo.txt").exists())
        self.assertEqual((self.klon / "requirements.txt").read_text(), "moje\n")

    def test_druga_grana_se_ne_dira(self):
        self.nova_verzija()
        self.git(self.klon, "checkout", "-q", "-b", "proba")
        self.assertIn("grani proba", azuriranje.azuriraj_izvor(folder=self.klon))
        self.assertFalse((self.klon / "novo.txt").exists())

    def test_tudj_repozitorijum_se_ne_dira(self):
        self.git(self.klon, "remote", "set-url", "origin", "https://example.com/drugo.git")
        self.assertIn("nije klon", azuriranje.azuriraj_izvor(folder=self.klon))

    def test_folder_bez_gita(self):
        self.assertIn("nije git klon", azuriranje.azuriraj_izvor(folder=self.koren))


if __name__ == "__main__":
    unittest.main()
