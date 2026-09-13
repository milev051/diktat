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


if __name__ == "__main__":
    unittest.main()
