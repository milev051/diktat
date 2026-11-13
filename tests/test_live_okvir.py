"""Okvir uzivo mora da prikaze i poslednji red, onaj koji se upravo izgovara."""
import unittest

import AppKit

from dictate import overlay


class LiveOkvirVisina(unittest.TestCase):
    def test_polje_je_dovoljno_visoko_za_sve_redove(self):
        AppKit.NSApplication.sharedApplication()
        panel = overlay.LivePanel()
        panel._build()
        reci = ("danas sam razgovarao sa klijentom o novom projektu i dogovorili "
                "smo se da sledece nedelje pocnemo sa radom na titlovima za "
                "emisiju koja ide utorkom uvece pa treba sve da bude spremno "
                "do ponedeljka a ja cu da proverim imena gostiju").split()
        tekst = ""
        try:
            for rec in reci:
                tekst = (tekst + " " + rec).strip()
                panel.set_text(tekst)
                visina = panel._panel.frame().size.height
                redovi = panel._view.redovi()
                dno = redovi[-1][0].origin.y + panel._view.visina_reda
                # Poslednji red (onaj koji se izgovara) mora da stane u prozor.
                self.assertGreaterEqual(visina, dno + 2 * overlay.TITL_PAD_Y, tekst)
                # Svaka traka ima isti luft gore i dole: trake se dodiruju
                # bez preklapanja, pa je razmak redova tacno visina trake.
                for (r1, _), (r2, _) in zip(redovi, redovi[1:]):
                    self.assertAlmostEqual(
                        r2.origin.y - r1.origin.y,
                        panel._view.visina_reda + 2 * overlay.TITL_PAD_Y, places=1)
                self.assertEqual(sum(o.length for _, o in redovi),
                                 panel._view.lm.numberOfGlyphs())
        finally:
            panel.hide()


if __name__ == "__main__":
    unittest.main()
