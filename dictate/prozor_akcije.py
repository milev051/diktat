"""Sta rade dugmad, prekidaci i polja u prozoru Podesavanja.

Sam prozor (raspored, kolone) je u settings_window.py; ovde je samo sta se
desi kad se nesto klikne.
"""

import subprocess
import threading
import time

import AppKit

from . import apitest, autostart, config, dijagnostika, hotkey, insert, rezerva, settings_window


class ProzorAkcije:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    def _open_settings(self, _):
        """Otvori desktop prozor sa istim grupama kao Android aplikacija."""
        self._zapamti_prethodnu()
        if self._settings_window_ui is None:
            self._settings_window_ui = settings_window.SettingsWindow(self)
        self._settings_window_ui.show()
        if self.cfg.get("transcription_provider") == "gemini_live":
            self._check_api_keys(None)
        # Svako otvaranje pita GitHub, ali ne cesce od jednom u minuti: dva
        # brza klika na ikonicu ne treba da budu dva zahteva.
        if (self.cfg.get("update_check", True) and not self._azur_radi
                and time.time() - self._azur_proveren_u > 60):
            self._azur_proveri(rucno=False)

    def _zapamti_prethodnu(self):
        """Zapamti aplikaciju u kojoj je korisnik bio pre prozora.

        Prozor je jos zatvoren kad se ovo zove, pa je ispred i dalje ta
        aplikacija. Ako je prozor vec ispred, pamti se ranija.
        """
        prednja = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        moja = AppKit.NSRunningApplication.currentApplication()
        if (prednja is not None
                and prednja.processIdentifier() != moja.processIdentifier()):
            self._pre_prozora = prednja

    def _nalepi_u_prethodnu(self):
        """Vrati fokus aplikaciji od pre prozora i nalepi clipboard.

        Lepi se tek kad ta aplikacija stvarno bude ispred, inace bi Cmd+V
        otisao u prazno. Gde nema polja za unos, Cmd+V ne radi nista.
        """
        cilj = self._pre_prozora
        if cilj is None or cilj.isTerminated():
            return
        cilj.activateWithOptions_(0)
        pid = cilj.processIdentifier()

        def radnik():
            rok = time.time() + 1.5
            while time.time() < rok:
                prednja = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
                if prednja is not None and prednja.processIdentifier() == pid:
                    insert.nalepi_clipboard()
                    return
                time.sleep(0.05)

        threading.Thread(target=radnik, daemon=True).start()

    def _toggle_settings(self):
        """Ikonica je prekidač: drugi klik sklanja prozor."""
        prozor = self._settings_window_ui
        if prozor is not None and prozor.visible():
            prozor.hide()
            return
        self._open_settings(None)

    def settingsCheckbox_(self, sender):
        key = str(sender.identifier() or "")
        value = sender.state() == AppKit.NSControlStateValueOn
        if key == "strip_punctuation":
            self.cfg["strip_punctuation"] = value
            self.cfg["samo_zarezi"] = False
        elif key == "punctuation":
            self.cfg["strip_punctuation"] = not value
            self.cfg["samo_zarezi"] = False
        elif key == "start_at_login":
            try:
                autostart.sync(value)
            except OSError as exc:
                self.state.set(phase="error", message=f"Automatsko pokretanje: {exc}")
                sender.setState_(AppKit.NSControlStateValueOn if self.cfg.get(key, True)
                                 else AppKit.NSControlStateValueOff)
                return
            self.cfg[key] = value
        elif key:
            self.cfg[key] = value
        config.save(self.cfg)
        if self._settings_window_ui is not None:
            self._settings_window_ui.refresh()

    def settingsPopup_(self, sender):
        key = str(sender.identifier() or "")
        title = str(sender.titleOfSelectedItem() or "")
        if key == "transcription_provider":
            self.cfg["transcription_provider"] = (
                settings_window.provider_from_title(title)
            )
            config.desktop_policy(self.cfg)
            if self.cfg["transcription_provider"] == "gemini_live":
                self._check_api_keys(None)
        elif key == "input_device":
            self.cfg["input_device"] = (
                None if title == settings_window.MIKROFON_PODRAZUMEVANI else title
            )
        config.save(self.cfg)
        if self._settings_window_ui is not None:
            self._settings_window_ui.refresh()

    def controlTextDidEndEditing_(self, notification):
        field = notification.object()
        key = str(field.identifier() or "")
        if key:
            self.cfg[key] = field.stringValue().strip()
            config.save(self.cfg)
            if key == "polish_api_key":
                self._check_api_keys(None)

    def _dugme_misa_snimljeno(self, vrsta, broj):
        """Zove se van tap niti kad korisnik pritisne dugme koje se snima."""
        self._mouse_learning = False
        if vrsta is None:
            self._mouse_escape_at = time.monotonic()
        self.mis_status = ""
        self.cfg["mouse_button"] = broj if vrsta == "mis" else None
        self.cfg["mouse_key_vk"] = broj if vrsta == "taster" else None
        self.cfg["mouse_swipe"] = broj if vrsta == "swipe" else None
        if vrsta is None:
            self.listener.iskljuci_dugme()
        config.save(self.cfg)
        self._mis_dirty = True

    def settingsButton_(self, sender):
        action = str(sender.identifier() or "")
        if action.startswith("copy_history_"):
            try:
                index = int(action.removeprefix("copy_history_"))
                # Razmak na kraju, kao posle diktata: sledeca rec se inace
                # zalepi za nalepljen tekst.
                value = self.upis.istorija()[index].rstrip() + " "
                insert.set_clipboard(value)
            except (ValueError, IndexError):
                return
            # Posle kopiranja prozor vise ne treba: sklanja se sam, a tekst se
            # nalepi u polje gde je bio fokus pre otvaranja.
            if self._settings_window_ui is not None:
                self._settings_window_ui.hide()
            self._nalepi_u_prethodnu()
        elif action == "update":
            self._azur_klik()
        elif action.startswith("prepisi_"):
            self._prepisi_sacuvan(int(action.removeprefix("prepisi_")))
        elif action.startswith("obrisi_"):
            sacuvani = rezerva.sacuvani(aktivni=self._aktivni_snimci())
            index = int(action.removeprefix("obrisi_"))
            if index < len(sacuvani):
                sacuvani[index].obrisi()
            self._sacuvani_dirty = True
        elif action == "mouse_learn":
            if self.listener.snimi_dugme(self._dugme_misa_snimljeno):
                self._mouse_learning = True
                self.mis_status = "Press mouse button (Esc clears)"
            else:
                self.mis_status = "Accessibility permission required"
            self._mis_dirty = True
        elif action == "mouse_off":
            self.cfg["mouse_button"] = None
            self.cfg["mouse_key_vk"] = None
            self.cfg["mouse_swipe"] = None
            config.save(self.cfg)
            self.mis_status = ""
            self.listener.iskljuci_dugme()
            self._mis_dirty = True
        elif action == "check_api":
            self._check_api_keys(sender)
        elif action == "open_live_log":
            dijagnostika.LIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
            dijagnostika.LIVE_LOG.touch(exist_ok=True)
            subprocess.Popen(["open", str(dijagnostika.LIVE_LOG)])
        elif action == "quit":
            self._quit(sender)
        elif action == "stop_recording":
            self._stop_from_menu(sender)
        elif action == "accessibility":
            subprocess.Popen([
                "open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            ])
        elif action == "microphone":
            subprocess.Popen([
                "open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
            ])

    def _procitaj_kljuceve_iz_polja(self):
        """Provera mora da vidi tekst u polju, ne stari config.json.

        Klik na dugme inace ume da krene pre nego sto polje zavrsi unos,
        pa se proveri prethodni kljuc.
        """
        ui = getattr(self, "_settings_window_ui", None)
        if ui is None or getattr(ui, "window", None) is None:
            return
        fields = {}
        for key in apitest.KEY_FIELDS:
            view = ui.controls.get(key)
            if view is not None and hasattr(view, "stringValue"):
                fields[key] = view.stringValue()
        if not fields:
            return
        apitest.apply_fields(self.cfg, fields)
        config.save(self.cfg)

    def _check_api_keys(self, _):
        self._procitaj_kljuceve_iz_polja()
        snapshot = {"polish_api_key": self.cfg.get("polish_api_key", "")}
        if (self._api_check_running
                and getattr(self, "_api_check_pending_key", None) == snapshot["polish_api_key"]):
            return
        generation = getattr(self, "_api_check_generation", 0) + 1
        self._api_check_generation = generation
        self._api_check_pending_key = snapshot["polish_api_key"]
        self._api_check_running = True
        self._api_check_status = ""
        self._api_check_result = None
        if self._settings_window_ui is not None:
            self._settings_window_ui.refresh_api_check()

        def worker():
            try:
                result = apitest.check_gemini(snapshot)
            except Exception:
                result = "Gemini: connection failed"
            # An old response must not mark a newly entered key as valid.
            if generation == self._api_check_generation:
                self._api_check_result = (generation, result)

        threading.Thread(target=worker, daemon=True).start()
