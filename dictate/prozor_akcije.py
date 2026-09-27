"""Sta rade dugmad, prekidaci i polja u prozoru Podesavanja.

Sam prozor (raspored, kolone) je u settings_window.py; ovde je samo sta se
desi kad se nesto klikne.
"""

import subprocess
import threading
import time

import AppKit

from . import apitest, config, insert, rezerva, settings_window


class ProzorAkcije:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    def _open_settings(self, _):
        """Otvori desktop prozor sa istim grupama kao Android aplikacija."""
        self._zapamti_prethodnu()
        if self._settings_window_ui is None:
            self._settings_window_ui = settings_window.SettingsWindow(self)
        self._settings_window_ui.show()
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
        if key == "text_style_written":
            self.cfg["text_style"] = "written" if value else "spoken"
        elif key == "pravilno":
            config.postavi_pravilno(self.cfg, value)
        elif key in ("hotkey_section", "hotkey_grave"):
            self.cfg[key] = value
            config.save(self.cfg)
            self._restart_hotkey()
        elif key == "lokalna_pravila":
            # Prekidač grupe je izvedeno stanje: ugašena grupa znači „pravilno",
            # tj. sva pravila ugašena, uz pamćenje zatečenog izbora.
            config.postavi_pravilno(self.cfg, not value)
        elif key == "ai_obrada":
            # Nije peto podesavanje nego precica nad alatima: gasenje pamti
            # zatecen izbor, paljenje ga vraca.
            config.postavi_ai_obradu(self.cfg, value)
        elif key == "debug":
            self.cfg["debug"] = value
            self._apply_debug(value)
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
            if self.cfg["transcription_provider"] == "openai":
                self.cfg["openai_output_script"] = "latin"
        elif key == "text_model":
            self.cfg["text_model"] = "groq" if title.startswith("Groq") else "gemini"
        elif key == "input_device":
            self.cfg["input_device"] = (
                None if title == "Sistemski podrazumevani" else title
            )
        elif key == "interpunkcija" and title in settings_window.INTERPUNKCIJA:
            strip, zarezi = settings_window.INTERPUNKCIJA[title]
            self.cfg["strip_punctuation"] = strip
            self.cfg["samo_zarezi"] = zarezi
        elif key == "mode":
            self.cfg["mode"] = "hold" if title == "Drži taster" else "toggle"
            if hasattr(self, "listener"):
                self.listener.mode = self.cfg["mode"]
        config.save(self.cfg)
        if self._settings_window_ui is not None:
            self._settings_window_ui.refresh()

    def controlTextDidEndEditing_(self, notification):
        field = notification.object()
        key = str(field.identifier() or "")
        if key:
            self.cfg[key] = field.stringValue().strip()
            config.save(self.cfg)

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
        elif action == "check_api":
            self._check_api_keys(sender)
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

    def _check_api_keys(self, _):
        if self._api_check_running:
            self.state.set(phase="thinking", message="Provera API ključeva već traje…")
            return
        self._api_check_running = True
        self.state.set(phase="thinking", message="Proveravam API ključeve…")

        def worker():
            try:
                result = "\n".join(apitest.check_all(self.cfg))
            except Exception as exc:  # noqa: BLE001
                result = f"Provera nije uspela: {exc}"
            self._api_check_result = result
            self._api_check_running = False

        threading.Thread(target=worker, daemon=True).start()
