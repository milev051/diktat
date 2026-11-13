"""Menu-bar aplikacija: taster -> diktat -> tekst u aktivnu aplikaciju.

Ovde je samo pokretanje, stanje i traka menija. Ostalo je po delovima, svaki
u svom fajlu, a DictateApp ih nasledjuje:

  snimanje.py          start, stop, osigurac, sesija, izbor servisa
  tok_google.py        Google: secenje na pauzama, segmenti
  tok_openai.py        OpenAI: ceo snimak posle Stop-a
  tok_gemini.py        Gemini Live: strim dok snimas, pregled uzivo
  upis.py              redosled i upis teksta, istorija
  obrada.py            lokalna pravila i AI obrada
  prozor_akcije.py     sta rade dugmad i prekidaci u Podesavanjima
  prepis_sacuvanog.py  Prepisi / Obrisi za sacuvane snimke
  azuriranje_ui.py     dugme i provera azuriranja
  zvuk.py              utisan racunar i pauziran plejer dok se snima

Niti:
  glavna       rumps / AppKit petlja + tajmer koji 20 puta u sekundi osvezava
               ikonicu, okvir i prozor
  pynput       event tap za taster
  mikrofon     cita zvuk nezavisno od mreze (`_tracked`)
  sesija       prepoznavanje jednog diktata

AppKit se dira iskljucivo iz glavne niti; radne niti samo upisuju u `State`.
"""

import threading
import time

import AppKit
import objc
import rumps

from . import (
    audio, autostart, config, debugdump, geministt, hotkey, insert, obrada, overlay,
    rezerva, settings_window, zvuk,
)
from .snimanje import Snimanje
from .tok_google import GoogleTok
from .tok_openai import OpenAiTok
from .tok_gemini import GeminiTok
from . import upis
from .istorija import Arhiva
from .obrada import Obrada
from .prozor_akcije import ProzorAkcije
from .prepis_sacuvanog import PrepisSacuvanog
from .azuriranje_ui import AzuriranjeUI

class _StatusClickDelegate(AppKit.NSObject):
    """Klik na ikonicu otvara podešavanja; drugi klik ih sklanja."""

    def initWithApp_(self, app):
        self = objc.super(_StatusClickDelegate, self).init()
        if self is not None:
            self._app = app
        return self

    def clicked_(self, _sender):
        self._app._toggle_settings()


class State:
    """Deljeno stanje izmedju radnih niti i UI niti."""

    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "idle"          # idle | recording | thinking | error
        self.message = ""            # tekst greske ili statusa za HUD
        self.dirty = True

    def set(self, **kw):
        with self.lock:
            for key, value in kw.items():
                setattr(self, key, value)
            self.dirty = True

    def snapshot(self):
        with self.lock:
            was_dirty = self.dirty
            self.dirty = False
            return self.phase, self.message, was_dirty


class DictateApp(
    Snimanje,
    GoogleTok,
    OpenAiTok,
    GeminiTok,
    Obrada,
    ProzorAkcije,
    PrepisSacuvanog,
    AzuriranjeUI,
    rumps.App,
):
    def __init__(self):
        super().__init__("Diktat", title="", quit_button=None)
        self.cfg = config.load()
        config.save(self.cfg)
        self.state = State()
        try:
            autostart.sync(self.cfg.get("start_at_login", True))
        except OSError as exc:
            self.state.set(phase="error", message=f"Start at login: {exc}")
        self.hud = overlay.Overlay(self.cfg.get("overlay_position", "bottom"))
        # Okvir sa prepisom uzivo stoji iznad pilule kad su oboje na dnu.
        self.live_panel = overlay.LivePanel(
            avoid_pill=bool(self.cfg.get("show_overlay", False))
            and self.cfg.get("overlay_position", "bottom") == "bottom"
        )
        self._live_text = ""
        self._live_text_dirty = False
        self._live_last_update_at = 0.0
        self._live_waiting = False
        self._live_trace = None
        self._live_diag_drawn_at = 0.0
        # Okvir se gasi u trenutku zaustavljanja. Zastavicu dize nit tastera, a
        # sklanja je `_tick` sa glavne niti; posle nje reader jos stize da
        # posalje poslednju potvrdjenu celinu, pa mora da postoji i zabrana da
        # je okvir ponovo prikaze.
        self._live_off = True

        self._client_error = None
        self.last_transcription_status = "No completed dictation yet."
        self.last_transcription_detail = ""
        self._session_lock = threading.Lock()
        self._recorder = None
        # Pokretanje ceka na oslobodjen mikrofon (do ~1.5s), pa STOP ume da
        # stigne pre nego sto `_recorder` uopste postoji. Bez ovog para
        # zastavica taj STOP nema sta da zaustavi, a snimanje krene odmah posle
        # njega i vise se ne prekida — taster tada deluje mrtav.
        self._starting = 0
        self._stop_requested = False
        self._policy_set = False
        self._status_click_set = False
        self._error_shown_at = None
        self._record_started_at = 0.0
        self._stats_lock = threading.Lock()
        self._dump = None
        self._debug_sessions = {}
        # Red za upis ima svoje stanje (tiketi, brojaci, istorija); ostatak
        # aplikacije ga koristi samo kroz njegove metode.
        self.upis = upis.RedUpisa(
            arhiva=Arhiva(), clipboard=lambda tekst: (
                insert.set_clipboard(tekst) if self.cfg.get("save_clipboard", False) else None
            ),
            cuvaj_clipboard=lambda: self.cfg.get("save_clipboard", False),
            upisi=lambda tekst: insert.insert(
                tekst,
                method=self.cfg.get("insert_method", "auto"),
                restore_clipboard=True,
            ),
            upisi_deo=self._apply_live_field_final,
            upisi_preview=self._apply_live_field_preview,
            kraj_live=insert.finish_live,
            on_wait=self._live_queue_wait,
            ceka_celinu=self._deferred,
            za_obradu=self._za_obradu,
            posle=self._posle_upisa,
        )
        self._session_seq = 0
        # Delovi diktata koji cekaju AI obradu, po sesiji (obrada.py).
        self.ceka_obradu = obrada.CekanjeObrade()
        self._api_check_result = None
        self._api_check_running = False
        self._api_check_generation = 0
        self._api_check_status = ""
        self._settings_window_ui = None
        # Sta je Diktat utisao ili pauzirao, da posle snimanja vrati samo to.
        self.tisina = zvuk.Tisina()
        # Aplikacija koja je bila ispred pre otvaranja prozora; u nju se lepi
        # tekst kliknut u istoriji.
        self._pre_prozora = None
        # Azuriranje: radna nit samo upisuje stanje i dize `_azur_dirty`, a
        # prozor i naslov osvezava `_tick` sa glavne niti.
        self._azur_izdanje = None
        self._azur_status = ""
        # Kratak ishod rucne provere za natpis dugmeta; pun tekst je u statusu.
        self._azur_ishod = ""
        self._azur_radi = False
        self._azur_dirty = False
        self._azur_restart = False
        self._azur_proveren_u = 0.0
        # Prvi poziv AVFoundation-a (provera dozvole za mikrofon) traje ~2s, a
        # gradnja prozora jos ~0.3s; oba su padala na prvi klik na ikonicu.
        # Zato se AVFoundation ucita u pozadini, a prozor napravi unapred.
        self._prozor_moze = False
        self._show_settings_on_launch = True
        self._sacuvani_dirty = True
        # Snimanje dugmeta misa: natpis u prozoru i znak da ga treba osveziti
        # (dugme stize iz tap niti, a prozor sme da se dira samo iz `_tick`).
        self.mis_status = ""
        self._mouse_learning = False
        self._mis_dirty = False
        self._prepis_radi = False
        self.prepis_status = ""
        # Ostatak neuspelog diktata od pre pokretanja: prozor se otvori sam,
        # da se prepis ponovi bez trazenja.
        self._najavi_sacuvane = False

        def zagrej():
            audio.microphone_granted()
            self._prozor_moze = True

        threading.Thread(target=zagrej, daemon=True).start()

        self._apply_debug(self.cfg.get("debug", False))
        self._preflight()
        self.upis.pokreni()

        self.listener = self._make_listener()

    def _make_listener(self):
        return hotkey.HotkeyListener(
            self.cfg,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_cancel=self._on_cancel,
            is_synthetic=insert.injecting,
        )

    def _restart_hotkey(self):
        """Ponovo otvori osluškivanje tastature.

        Gutanje `§` traži AKTIVAN event tap, a vrsta tapa se bira pri otvaranju,
        pa se prekidač ne može uključiti bez ponovnog otvaranja.
        """
        stari = getattr(self, "listener", None)
        if stari is not None:
            stari.stop()
        self.listener = self._make_listener()
        self.listener.start()

    # ------------------------------------------------------------------ UI


    # ------------------------------------------------------- preflight

    def _preflight(self):
        if not hotkey.accessibility_granted():
            msg = (
                "Nema Accessibility dozvole — hotkey nece raditi. "
                "System Settings > Privacy & Security > Accessibility."
            )
            self._client_error = msg
            self.state.set(phase="error", message=msg)

    # ------------------------------------------------- hotkey callbacks


    # --------------------------------------------------------- sesija


    def _consume_api_check(self):
        result = self._api_check_result
        if result is None:
            return
        self._api_check_result = None
        generation, status = result
        if generation != self._api_check_generation:
            return
        self._api_check_running = False
        self._api_check_status = status
        if self._settings_window_ui is not None:
            self._settings_window_ui.refresh_api_check()

    # ----------------------------------------------------------- timer

    @rumps.timer(0.05)
    def _tick(self, _sender):
        if not self._policy_set:
            AppKit.NSApplication.sharedApplication().setActivationPolicy_(
                AppKit.NSApplicationActivationPolicyAccessory
            )
            self._policy_set = True
        if not self._status_click_set:
            self._configure_status_click()

        self._consume_api_check()

        # Istoriju puni radna nit, a prozor sme da se dira samo odavde.
        if self.upis.istorija_promenjena():
            if self._settings_window_ui is not None:
                self._settings_window_ui.refresh()
        if self._settings_window_ui is not None:
            self._settings_window_ui.refresh_recording()

        self._tick_live_panel()
        self._tick_azuriranje()
        if self._prozor_moze and self._settings_window_ui is None:
            self._settings_window_ui = settings_window.SettingsWindow(self)
            self._settings_window_ui.pripremi()
        if self._show_settings_on_launch and self._settings_window_ui is not None:
            self._show_settings_on_launch = False
            self._open_settings(None)
        if self._najavi_sacuvane and self._settings_window_ui is not None:
            self._najavi_sacuvane = False
            self._open_settings(None)
        if self._mis_dirty:
            self._mis_dirty = False
            if self._settings_window_ui is not None:
                self._settings_window_ui.refresh()
        if self._sacuvani_dirty:
            self._sacuvani_dirty = False
            if self._settings_window_ui is not None:
                self._settings_window_ui.refresh()

        self.state.snapshot()
        if self._azur_dirty:
            self._azur_dirty = False
            if self._settings_window_ui is not None:
                self._settings_window_ui.refresh()

    def _configure_status_click(self):
        """Keep the app running without a menu bar item or recording counter."""
        nsapp = getattr(self, "_nsapp", None)
        item = getattr(nsapp, "nsstatusitem", None) if nsapp else None
        if item is not None:
            item.setVisible_(False)
            self._status_click_set = True

    # -------------------------------------------------- menu callbacks


    # ------------------------------------------------------ rezervni snimci


    # ---------------------------------------------------------- azuriranje


    def _apply_debug(self, on):
        self._dump = (
            debugdump.DebugDump(
                self.cfg.get("debug_dir", "~/Diktat-debug"), self.cfg["sample_rate"]
            )
            if on
            else None
        )

    def ponovo_pokreni(self):
        """Ugasi ovaj proces i otvori Diktat iznova.

        Ako prepis još stoji samo na ekranu, prvo se čuva u istoriji i predaje za upis.
        """
        tekst = (getattr(self, "_live_text", "") or "").strip()
        if self._recorder is not None:
            self._unesi_vidljivi_prepis()
            self._on_stop()
        import subprocess
        import sys
        from pathlib import Path
        bundle = AppKit.NSBundle.mainBundle()
        putanja = str(bundle.bundlePath() or "") if bundle is not None else ""
        if putanja.endswith(".app"):
            subprocess.Popen(["open", "-n", putanja])
        else:
            koren = Path(__file__).resolve().parent.parent
            subprocess.Popen([sys.executable, str(koren / "run.py")])
        self._quit(None)

    def _quit(self, _):
        if self._recorder is not None:
            self._unesi_vidljivi_prepis()
        # Racunar ne sme da ostane utisan zato sto je Diktat ugasen usred snimanja.
        self.tisina.vrati_odmah()
        try:
            self.listener.stop()
        finally:
            rumps.quit_application()

    # ------------------------------------------------------------- run

    def run(self, **kw):
        self.listener.start()
        super().run(**kw)



def main():
    # Kod na disku može biti ažuriran dok stari proces još radi. Ova oznaka
    # u logu potvrđuje tačno koji je kod zaista učitan pri pokretanju.
    import hashlib
    import faulthandler
    import signal
    from pathlib import Path
    folder = Path(__file__).parent
    digest = hashlib.sha256(b"".join(
        (folder / name).read_bytes()
        for name in ("app.py", "audio.py", "snimanje.py", "geministt.py", "wsock.py", "insert.py", "upis.py", "istorija.py", "tok_gemini.py")
    )).hexdigest()[:12]
    print(f"[diktat] učitan kod {digest}", flush=True)
    faulthandler.enable(all_threads=True)
    # Poslednji pad je SIGTRAP u nativnoj biblioteci. Uz macOS .ips treba i
    # Python stek svih niti, da se vidi koja je naša operacija bila u toku.
    faulthandler.register(signal.SIGTRAP, all_threads=True, chain=True)
    DictateApp().run()
