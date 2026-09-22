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

Niti:
  glavna       rumps / AppKit petlja + tajmer koji 20 puta u sekundi osvezava
               ikonicu, okvir i prozor
  pynput       event tap za taster
  mikrofon     cita zvuk nezavisno od mreze (`_tracked`)
  sesija       prepoznavanje jednog diktata

AppKit se dira iskljucivo iz glavne niti; radne niti samo upisuju u `State`.
"""

import queue
import threading
import time

import AppKit
import objc
import rumps
from Foundation import NSAttributedString

from . import (
    audio, config, debugdump, geministt, hotkey, insert, overlay, rezerva,
    settings_window,
)
from .snimanje import Snimanje
from .tok_google import GoogleTok
from .tok_openai import OpenAiTok
from .tok_gemini import GeminiTok
from .upis import Upis
from .obrada import Obrada
from .prozor_akcije import ProzorAkcije
from .prepis_sacuvanog import PrepisSacuvanog
from .azuriranje_ui import AzuriranjeUI

# Dok snima, naslov je proteklo vreme u sekundama ("07") umesto ikonice.
ICON = {
    "idle": "00",
    "error": "⚠️",
}
RED_AFTER = 15.0   # upozorenje važi samo za kratki režim

# Naranđasta umesto ciste zute: zuta je na svetlom menu baru jedva citljiva.
TITLE_COLORS = {
    "recording": AppKit.NSColor.systemRedColor,
    "busy": AppKit.NSColor.systemOrangeColor,
    "polishing": AppKit.NSColor.systemBlueColor,
}

ERROR_HUD_SECONDS = 4.0


class _StatusClickDelegate(AppKit.NSObject):
    """Klik na ikonicu otvara podešavanja; drugi klik ih sklanja."""

    def initWithApp_(self, app):
        self = objc.super(_StatusClickDelegate, self).init()
        if self is not None:
            self._app = app
        return self

    def clicked_(self, _sender):
        if self._app._recorder is not None or self._app._starting:
            self._app._stop_from_menu(None)
        else:
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
    Upis,
    Obrada,
    ProzorAkcije,
    PrepisSacuvanog,
    AzuriranjeUI,
    rumps.App,
):
    def __init__(self):
        super().__init__("Diktat", title=ICON["idle"], quit_button=None)
        self.cfg = config.load()
        self.state = State()
        self.hud = overlay.Overlay(self.cfg.get("overlay_position", "bottom"))
        # Okvir sa prepisom uzivo stoji iznad pilule kad su oboje na dnu.
        self.live_panel = overlay.LivePanel(
            avoid_pill=bool(self.cfg.get("show_overlay", False))
            and self.cfg.get("overlay_position", "bottom") == "bottom"
        )
        self._live_text = ""
        self._live_text_dirty = False
        # Okvir se gasi u trenutku zaustavljanja. Zastavicu dize nit tastera, a
        # sklanja je `_tick` sa glavne niti; posle nje reader jos stize da
        # posalje poslednju potvrdjenu celinu, pa mora da postoji i zabrana da
        # je okvir ponovo prikaze.
        self._live_off = True

        self._client_error = None
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
        self._last_clock = ""
        self._menubar = (None, None)
        self._count_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._pending = 0        # snimci koji se prepoznaju
        self._ticket = 0         # redni broj segmenta za ubacivanje
        self._insert_q: queue.Queue = queue.Queue()
        self._dump = None
        self._debug_sessions = {}
        self._hist_lock = threading.Lock()
        self._history: list[str] = []
        self._history_dirty = True
        # Sve sto ceka kraj diktata drzi se PO SESIJI: nov diktat sme da pocne
        # dok se prethodni jos obradjuje, pa bi u zajednickoj kanti dva diktata
        # zavrsila u jednom pozivu i zalepila se spojena.
        self._session_seq = 0
        self._formal_lock = threading.Lock()
        self._formal_parts: dict[int, list[str]] = {}
        self._pending_by: dict[int, int] = {}
        # Zvuk segmenata; unutrasnji kljuc je ticket, da redosled ostane
        # hronoloski i kad se segmenti prepoznaju paralelno.
        self._polishing = False
        self._polishing_count = 0
        self._api_check_result = None
        self._api_check_running = False
        self._settings_window_ui = None
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
        self._sacuvani_dirty = True
        self._prepis_radi = False
        self.prepis_status = ""
        # Ostatak neuspelog diktata od pre pokretanja: prozor se otvori sam,
        # da se prepis ponovi bez trazenja.
        self._najavi_sacuvane = bool(rezerva.sacuvani())

        def zagrej():
            audio.microphone_granted()
            self._prozor_moze = True

        threading.Thread(target=zagrej, daemon=True).start()

        self._apply_debug(self.cfg.get("debug", False))
        self._preflight()
        threading.Thread(target=self._insert_worker, daemon=True).start()

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

        if self._api_check_result is not None:
            result = self._api_check_result
            self._api_check_result = None
            rumps.alert(
                title="Provera API ključeva",
                message=result + "\n\nProvera ne šalje audio i ne troši minute transkripcije.",
            )

        # Istoriju puni radna nit, a prozor sme da se dira samo odavde.
        if self._history_dirty:
            self._history_dirty = False
            if self._settings_window_ui is not None:
                self._settings_window_ui.refresh()
        if self._settings_window_ui is not None:
            self._settings_window_ui.refresh_recording()

        self._tick_live_panel()
        self._tick_azuriranje()
        if (self._prozor_moze and self._settings_window_ui is None
                and self._recorder is None and not self._starting):
            self._settings_window_ui = settings_window.SettingsWindow(self)
            self._settings_window_ui.pripremi()
        if self._najavi_sacuvane and self._settings_window_ui is not None:
            self._najavi_sacuvane = False
            self._open_settings(None)
        if self._sacuvani_dirty:
            self._sacuvani_dirty = False
            if self._settings_window_ui is not None:
                self._settings_window_ui.refresh()

        phase, message, dirty = self.state.snapshot()

        # Auto-sklanjanje HUD-a sa greskom mora da radi i kad se stanje ne menja.
        if phase == "error" and self._error_shown_at is not None:
            if time.monotonic() - self._error_shown_at > ERROR_HUD_SECONDS:
                self.hud.hide()
        elif phase != "error":
            self._error_shown_at = None

        # Dok mikrofon radi, sat ide — bez obzira na to sta pise u `state`.
        # Prethodni diktat sme da se obradjuje paralelno, a njegova faza je
        # ranije preuzimala prikaz: naslov bi stao na "AI", brojanje bi se
        # zamrzlo i delovalo bi da aplikacija ne registruje govor.
        if self._recorder is not None:
            clock = self._clock_text()
            self._last_clock = clock   # ostaje i dok se posle obradjuje
            self._set_menubar(clock, self._title_color())
            if self.cfg.get("show_overlay", True):
                if not self.hud.visible:
                    self.hud.show(clock, mono=True)
                else:
                    self.hud.set_text(clock, mono=True)
                self.hud.set_state("recording")
                with self._count_lock:
                    pending = self._pending
                self.hud.set_busy(pending > 0)
            return

        if self._azur_dirty:
            self._azur_dirty = False
            dirty = True
            if self._settings_window_ui is not None:
                self._settings_window_ui.refresh()

        if not dirty:
            return

        # U naslovu su UVEK cifre; stanje se vidi po boji. Tekst umesto brojeva
        # je gutao sat, pa se nije videlo koliko traje ni koliko je ostalo.
        if phase == "polishing":
            self._set_menubar(self._last_clock or ICON["idle"], "polishing")
        elif phase == "thinking":
            self._set_menubar(self._last_clock or ICON["idle"], "busy")
        else:
            naslov = ICON.get(phase, ICON["idle"])
            if phase != "error" and self.azur_dostupno():
                # Strelica je jedini znak da ima nove verzije; ne iskace nista.
                naslov += " ↑"
            self._set_menubar(naslov)

        if not self.cfg.get("show_overlay", True):
            return

        if phase in ("recording", "thinking"):
            # Pilula nosi samo vreme; posle pustanja tastera ono se zamrzne
            # i stoji dok obrada ne prodje.
            shown = self._last_clock or "0:00"
            if not self.hud.visible:
                self.hud.show(shown, mono=True)
            else:
                self.hud.set_text(shown, mono=True)
            self.hud.set_state("recording" if phase == "recording" else "processing")
        elif phase == "error":
            # Greska se pokaze kratko pa se skloni; poruka ostaje u meniju.
            if self._error_shown_at is None:
                self._error_shown_at = time.monotonic()
                self.hud.show(message[:90], mono=False)
                self.hud.set_state("error")
        else:
            self.hud.hide()


    def _clock_text(self) -> str:
        """Proteklo vreme u sekundama, dve cifre. Snimanje ionako staje na
        granici, pa minuti nemaju sta da rade u naslovu."""
        elapsed = time.monotonic() - self._record_started_at
        return f"{min(int(elapsed), int(self._limit_seconds())):02d}"

    def _configure_status_click(self):
        nsapp = getattr(self, "_nsapp", None)
        item = getattr(nsapp, "nsstatusitem", None) if nsapp else None
        button = item.button() if item is not None else None
        if button is None:
            return
        self._status_click_delegate = _StatusClickDelegate.alloc().initWithApp_(self)
        item.setMenu_(None)
        button.setTarget_(self._status_click_delegate)
        button.setAction_("clicked:")
        self._status_click_set = True

    def _title_color(self):
        """Boja kaze sta se trenutno desava; cifre uvek stoje.

        Plava (model) ima prednost nad narandzastom (prepoznavanje), a obe nad
        crvenom (blizu granice) — jer je cekanje na tudji odgovor vaznije od
        toga koliko dugo traje ovaj snimak.
        """
        if self._polishing:
            return "polishing"
        with self._count_lock:
            if self._pending > 0:
                return "busy"
        # OpenAI ima duži sigurnosni limit; crvena boja posle 15 s bi izgledala
        # kao greška iako snimanje normalno traje. Obrada se i dalje prikazuje
        # narandžasto preko `busy`, a model plavo preko `polishing`.
        if self.cfg.get("transcription_provider", "google") == "openai" or (
            geministt.enabled(self.cfg)
        ):
            return None
        if self._segmenting():
            # Neprekidni Google režim nema granicu od 30 s po diktatu.
            return None
        elapsed = time.monotonic() - self._record_started_at
        return "recording" if elapsed >= RED_AFTER else None

    def _set_menubar(self, text: str, color=None):
        """rumps.title ne ume boju, pa naslov ide kao attributed string.

        Cifre su u monospacedDigit fontu — inace se sirina naslova menja svakom
        promenom sekunde i ostale ikonice u menu baru poskakuju.
        """
        if (text, color) == self._menubar:
            return
        self._menubar = (text, color)
        nsapp = getattr(self, "_nsapp", None)
        item = getattr(nsapp, "nsstatusitem", None) if nsapp else None
        button = item.button() if item is not None else None
        if button is None:
            self.title = text        # pre nego sto rumps napravi status stavku
            return
        attrs = {
            AppKit.NSFontAttributeName:
                AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(
                    0, AppKit.NSFontWeightRegular
                )
        }
        if color is not None:
            attrs[AppKit.NSForegroundColorAttributeName] = TITLE_COLORS[color]()
        button.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        )


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

    def _quit(self, _):
        try:
            self.listener.stop()
        finally:
            rumps.quit_application()

    # ------------------------------------------------------------- run

    def run(self, **kw):
        self.listener.start()
        super().run(**kw)



def main():
    DictateApp().run()
