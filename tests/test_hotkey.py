"""Prekidač za diktat: izabrani modifikator i taster `§`."""

import unittest

from pynput import keyboard

from dictate import hotkey

class TasterSekcije(unittest.TestCase):
    """`§` kao drugi prekidač: prepoznaje se po `vk`, guta se samo bez modifikatora."""

    def _listener(self, **kw):
        cfg = {"hotkey": "alt_r", "mode": "toggle", "min_seconds": 0.35}
        cfg.update(kw)
        return hotkey.HotkeyListener(
            cfg, on_start=lambda: True, on_stop=lambda: None, on_cancel=lambda *a: None
        )

    def test_prepoznaje_se_po_vk(self):
        self.assertTrue(hotkey.is_section_key(keyboard.KeyCode.from_vk(hotkey.SECTION_VK)))
        self.assertFalse(hotkey.is_section_key(keyboard.KeyCode.from_char("a")))

    def test_pokrece_snimanje(self):
        sluzba = self._listener()
        sluzba._on_press(keyboard.KeyCode.from_vk(hotkey.SECTION_VK))
        self.assertTrue(sluzba._active)

    def test_uz_modifikator_nije_prekidac(self):
        # Shift+§ daje „±"; taj znak korisnik i dalje sme da otkuca.
        sluzba = self._listener()
        sluzba._on_press(keyboard.Key.shift)
        sluzba._on_press(keyboard.KeyCode.from_vk(hotkey.SECTION_VK))
        self.assertFalse(sluzba._active)

    def test_iskljucen_prekidac_ne_reaguje(self):
        sluzba = self._listener(hotkey_section=False)
        sluzba._on_press(keyboard.KeyCode.from_vk(hotkey.SECTION_VK))
        self.assertFalse(sluzba._active)

    def test_izabrani_modifikator_i_dalje_radi(self):
        sluzba = self._listener(hotkey_section=False)
        sluzba._on_press(keyboard.Key.alt_r)
        self.assertTrue(sluzba._active)


class TasterGrave(unittest.TestCase):
    """`` ` `` kao treci prekidac: podrazumevano iskljucen, nezavisan od `§`."""

    def _listener(self, **kw):
        cfg = {"hotkey": "alt_r", "mode": "toggle", "min_seconds": 0.35}
        cfg.update(kw)
        return hotkey.HotkeyListener(
            cfg, on_start=lambda: True, on_stop=lambda: None, on_cancel=lambda *a: None
        )

    def _grave(self):
        return keyboard.KeyCode.from_vk(hotkey.GRAVE_VK)

    def test_podrazumevano_ne_reaguje(self):
        sluzba = self._listener()
        sluzba._on_press(self._grave())
        self.assertFalse(sluzba._active)

    def test_ukljucen_pokrece_i_zaustavlja(self):
        sluzba = self._listener(hotkey_grave=True, hotkey_section=False)
        sluzba._on_press(self._grave())
        self.assertTrue(sluzba._active)
        sluzba._on_press(self._grave())
        self.assertFalse(sluzba._active)

    def test_uz_shift_nije_prekidac(self):
        # Shift+` daje „~"; taj znak korisnik i dalje sme da otkuca.
        sluzba = self._listener(hotkey_grave=True)
        sluzba._on_press(keyboard.Key.shift)
        sluzba._on_press(self._grave())
        self.assertFalse(sluzba._active)

    def test_guta_se_samo_izabrano(self):
        self.assertEqual(self._listener().znak_tasteri(), {hotkey.SECTION_VK})
        self.assertEqual(
            self._listener(hotkey_grave=True, hotkey_section=False).znak_tasteri(),
            {hotkey.GRAVE_VK},
        )
        self.assertEqual(self._listener(hotkey_section=False).znak_tasteri(), set())


class NoviPritisakUTokuRepa(unittest.TestCase):
    """Stop, pa odmah nov diktat dok rep prethodnog jos traje.

    Oslobadjanje prethodnog snimanja zove `reset`. Ranije je brisalo i nov
    pritisak, pa sledeci nije mogao da zaustavi snimanje do granice od 120s.
    """

    def _listener(self):
        cfg = {"hotkey": "alt_r", "mode": "toggle", "min_seconds": 0.35}
        return hotkey.HotkeyListener(
            cfg, on_start=lambda: True, on_stop=lambda: None, on_cancel=lambda *a: None
        )

    def test_nov_pritisak_prezivi_oslobadjanje_starog(self):
        sluzba = self._listener()
        sluzba._on_press(keyboard.Key.alt_r)        # START prvog diktata
        pokrenuto_prvo = sluzba._pressed_at + 0.01  # mikrofon se otvori posle pritiska
        sluzba._on_press(keyboard.Key.alt_r)        # STOP, rep traje
        sluzba._pressed_at = pokrenuto_prvo + 0.3
        sluzba._active = True                       # START drugog, u toku repa
        sluzba.reset(pokrenuto=pokrenuto_prvo)      # prvi se tek sad oslobadja
        self.assertTrue(sluzba._active)
        sluzba._on_press(keyboard.Key.alt_r)        # mora da bude STOP
        self.assertFalse(sluzba._active)

    def test_granica_i_dalje_vraca_u_mirovanje(self):
        sluzba = self._listener()
        sluzba._on_press(keyboard.Key.alt_r)
        sluzba.reset(pokrenuto=sluzba._pressed_at + 0.01)
        self.assertFalse(sluzba._active)

    def test_bez_trenutka_uvek_vraca(self):
        # Zaustavljanje misem nema snimanje sa kojim bi se poredilo.
        sluzba = self._listener()
        sluzba._on_press(keyboard.Key.alt_r)
        sluzba.reset()
        self.assertFalse(sluzba._active)


if __name__ == "__main__":
    unittest.main()


class DugmeMisa(unittest.TestCase):
    """Snimljeno dugme miša radi kao prekidač i guta se; ostala dugmad prolaze."""

    def _listener(self, **kw):
        cfg = {"hotkey": "alt_r", "mode": "toggle", "min_seconds": 0.0}
        cfg.update(kw)
        self.dogadjaji = []
        return hotkey.HotkeyListener(
            cfg, on_start=lambda: self.dogadjaji.append("start"),
            on_stop=lambda: self.dogadjaji.append("stop"),
            on_cancel=lambda *a: self.dogadjaji.append("cancel"),
        )

    def _pritisni(self, sluzba, broj, tip):
        stari = hotkey.CGEventGetIntegerValueField
        hotkey.CGEventGetIntegerValueField = lambda _e, _f: broj
        try:
            return sluzba._mis_dogadjaj(None, tip, "dogadjaj", None)
        finally:
            hotkey.CGEventGetIntegerValueField = stari

    def test_nevazeci_broj_je_iskljuceno(self):
        self.assertIsNone(self._listener(mouse_button=0).mouse_button)
        self.assertIsNone(self._listener(mouse_button="3").mouse_button)
        self.assertEqual(self._listener(mouse_button=3).mouse_button, 3)

    def test_snimanje_pamti_i_guta_dugme(self):
        sluzba = self._listener()
        sluzba._pokreni_mis = lambda: None
        snimljeno = []
        sluzba.snimi_dugme(snimljeno.append)
        self.assertIsNone(self._pritisni(sluzba, 3, hotkey.kCGEventOtherMouseDown))
        self.assertIsNone(self._pritisni(sluzba, 3, hotkey.kCGEventOtherMouseUp))
        self.assertEqual(sluzba.mouse_button, 3)
        self.assertFalse(sluzba._active)   # snimanje ne pokreće diktat

    def test_izabrano_dugme_je_prekidac(self):
        sluzba = self._listener(mouse_button=2)
        self.assertIsNone(self._pritisni(sluzba, 2, hotkey.kCGEventOtherMouseDown))
        self.assertTrue(sluzba._active)
        self._pritisni(sluzba, 2, hotkey.kCGEventOtherMouseUp)
        self.assertTrue(sluzba._active)    # prekidač: puštanje ne zaustavlja
        self._pritisni(sluzba, 2, hotkey.kCGEventOtherMouseDown)
        self.assertFalse(sluzba._active)

    def test_drzi_taster_zaustavlja_na_pustanje(self):
        sluzba = self._listener(mouse_button=3, mode="hold")
        self._pritisni(sluzba, 3, hotkey.kCGEventOtherMouseDown)
        self.assertTrue(sluzba._active)
        self._pritisni(sluzba, 3, hotkey.kCGEventOtherMouseUp)
        self.assertFalse(sluzba._active)

    def test_drugo_dugme_prolazi(self):
        sluzba = self._listener(mouse_button=3)
        self.assertEqual(self._pritisni(sluzba, 2, hotkey.kCGEventOtherMouseDown), "dogadjaj")
        self.assertFalse(sluzba._active)
