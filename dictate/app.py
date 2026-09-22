"""Menu-bar aplikacija: drzi desni Command -> diktat -> tekst u aktivnu aplikaciju.

Niti:
  glavna       — rumps / AppKit petlja + Timer koji na 20 Hz osvezava ikonicu i HUD
  pynput       — event tap za hotkey
  sesija       — snimanje + gRPC stream ka Google-u (jedna po diktatu)

AppKit se dira iskljucivo iz glavne niti; radne niti samo upisuju u `State`.
"""

import queue
from collections import deque
import re
import subprocess
import threading
import time
import traceback

import AppKit
import objc
import rumps
from Foundation import NSAttributedString

from . import (
    abbrev, apitest, audio, azuriranje, config, debugdump, geministt, hotkey, insert,
    overlay, openai, polish, groq, rezerva, settings_window, webstt,
)

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
LIVE_MREZNI_ROK = 20
# Koliko posle repa STOP sme da ceka pre nego sto osigurac oslobodi mikrofon.
STOP_ROK = 3.0


class _MicDelegate(AppKit.NSObject):
    """Osvezava listu mikrofona svaki put kad se podmeni otvori.

    Bez ovoga lista ostaje onakva kakva je bila pri pokretanju, pa slusalice
    prikljucene u medjuvremenu nema u meniju. Sam SNIMAK to ne pogadja —
    uredjaji se osvezavaju pred svaki diktat — ali izbor u meniju laze.
    """

    def initWithApp_(self, app):
        self = objc.super(_MicDelegate, self).init()
        if self is None:
            return None
        self._app = app
        return self

    def menuNeedsUpdate_(self, menu):  # noqa: N802 - ime trazi AppKit
        try:
            self._app.refresh_mic_list()
        except Exception:  # noqa: BLE001 - delegat ne sme da obori meni
            traceback.print_exc()


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


class DictateApp(rumps.App):
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

        self._build_menu()
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

    def _build_menu(self):
        # Izlaz u nuzdi: prekidac ume da se razidje sa snimanjem (brz start pa
        # odmah stop), pa mora da postoji nacin da se snimanje zaustavi misem.
        # Stoji na prvom nivou, jer se trazi bas kad taster ne radi, i skriva
        # se dok se ne snima — stavka koja nema sta da uradi samo smeta.
        self.item_stop = rumps.MenuItem(
            "Zaustavi snimanje", callback=self._stop_from_menu
        )
        self.settings_item = rumps.MenuItem(
            "Podešavanja…", callback=self._open_settings
        )
        self.history_menu = rumps.MenuItem("Istorija")
        self.mic_menu = rumps.MenuItem("Mikrofon")

        # Meni je grupisan po pitanju na koje odgovaras, a ne po tome kad je
        # sta nastalo: Snimanje (kako), Tekst (kako izgleda), AI (sta model radi).
        snimanje_menu = rumps.MenuItem("Snimanje")
        self.item_hold = rumps.MenuItem("Drži taster", callback=self._set_hold)
        self.item_toggle = rumps.MenuItem("Prekidač", callback=self._set_toggle)
        # Neprekidno je nezavisno od nacina aktivacije: bira se koliko dugo
        # snima, a ne kako se pokrece.
        self.item_continuous = rumps.MenuItem(
            "Neprekidno (bez granice)", callback=self._toggle_continuous
        )
        self.item_recorded = rumps.MenuItem("Ukupno snimljeno: 0 s")
        for stavka in (
            self.item_hold, self.item_toggle, None, self.item_continuous,
            self.item_recorded,
        ):
            snimanje_menu.add(stavka if stavka is not None else rumps.separator)

        # "Sredjeno" je posao koji radi model, pa ostaje u AI grupi.
        self.item_tidy = rumps.MenuItem(
            "Sredi tekst (tačke i velika slova)", callback=self._toggle_tidy
        )

        # Ova dva radi nas kod, bez modela i bez kljuca — zato imaju svoj
        # podmeni i rade i kad je AI iskljucen.
        tekst_menu = rumps.MenuItem("Tekst")
        self.item_ascii = rumps.MenuItem(
            "Bez kvačica (č ć ž š → c c z s)", callback=self._toggle_ascii
        )
        self.item_abbrev = rumps.MenuItem(
            "Skraćuj česte fraze (ne znam → nzm)",
            callback=self._make_polish_toggle("abbreviations", True),
        )
        self.item_lowercase = rumps.MenuItem(
            "Sva slova mala", callback=lambda _: self._toggle_local_text("lowercase")
        )
        self.item_punctuation = rumps.MenuItem(
            "Ukloni interpunkciju (brojevi ostaju)",
            callback=lambda _: self._toggle_local_text("strip_punctuation"),
        )
        # Nad-prekidac iznad ta cetiri. Nije peto podesavanje nego precica:
        # cetiri klika za prelazak izmedju „kako sam izgovorio" i „pravopisno"
        # su cetiri prilike da se jedan zaboravi, pa tekst izadje na pola puta.
        self.item_pravilno = rumps.MenuItem(
            "Pravilno (gasi sva četiri ispod)", callback=self._toggle_pravilno
        )
        tekst_menu.add(self.item_pravilno)
        tekst_menu.add(rumps.separator)
        for stavka in (
            self.item_lowercase, self.item_punctuation, self.item_ascii,
            self.item_abbrev,
        ):
            tekst_menu.add(stavka)

        # Sve sto model radi je na jednom mestu, ali u dva bloka: prepoznavanje
        # (sporo, salje zvuk) i obrada teksta (brzo, salje samo tekst).
        # Nema glavnog prekidaca: izabran alat sam po sebi znaci da se AI
        # koristi. Prekidac je bio jos jedan korak koji nista nije odlucivao.
        ai_menu = rumps.MenuItem("AI")
        self.item_provider_google = rumps.MenuItem(
            "Transkripcija: Google", callback=lambda _: self._set_transcription_provider("google")
        )
        self.item_provider_openai = rumps.MenuItem(
            "Transkripcija: OpenAI GPT", callback=lambda _: self._set_transcription_provider("openai")
        )
        # Gemini 3.5 Transcribe Live: isti kljuc kao AI obrada, ali ZASEBAN
        # izbor — prepoznavanje i obrada teksta su dve razlicite stvari.
        self.item_provider_gemini_live = rumps.MenuItem(
            "Transkripcija: Gemini 3.5 Transcribe Live",
            callback=lambda _: self._set_transcription_provider("gemini_live"),
        )
        self.item_openai_long = rumps.MenuItem(
            "OpenAI dugi diktat (do 60 min)", callback=self._toggle_openai_long
        )
        text_model_menu = rumps.MenuItem("Model za manipulaciju teksta")
        self.item_text_model_gemini = rumps.MenuItem(
            "Gemini", callback=lambda _: self._set_text_model("gemini")
        )
        self.item_text_model_groq = rumps.MenuItem(
            "Groq GPT-OSS 120B", callback=lambda _: self._set_text_model("groq")
        )
        text_model_menu.add(self.item_text_model_gemini)
        text_model_menu.add(self.item_text_model_groq)
        api_keys_menu = rumps.MenuItem("API ključevi")
        self.item_gemini_key = rumps.MenuItem(
            "Gemini API ključ…", callback=self._set_gemini_key
        )
        self.item_openai_key = rumps.MenuItem(
            "OpenAI API ključ…", callback=self._set_openai_key
        )
        self.item_groq_key = rumps.MenuItem(
            "Groq API ključ…", callback=self._set_groq_key
        )
        self.item_check_api_keys = rumps.MenuItem(
            "Proveri sve API ključeve", callback=self._check_api_keys
        )
        for key_item in (self.item_gemini_key, self.item_groq_key, self.item_openai_key):
            api_keys_menu.add(key_item)
        api_keys_menu.add(self.item_check_api_keys)
        self.item_debug = rumps.MenuItem(
            "Detaljan log obrade", callback=self._toggle_debug
        )
        self.item_debug_open = rumps.MenuItem(
            "Otvori poslednji log…", callback=self._open_debug_log
        )
        self.item_polish_para = rumps.MenuItem(
            "Podeli na pasuse",
            callback=self._make_polish_toggle("polish_paragraphs", True),
        )
        self.item_polish_bullets = rumps.MenuItem(
            "Sažmi u tačke",
            callback=self._make_polish_toggle("polish_bullets", False),
        )
        self.item_polish_dedupe = rumps.MenuItem(
            "Izbaci ponavljanja",
            callback=self._make_polish_toggle("polish_dedupe", False),
        )
        # Bez callback-a: stavka je samo prikaz. Google ne nudi nacin da se vidi
        # preostala kvota, pa aplikacija broji svoje pozive sama.
        self.item_polish_count = rumps.MenuItem("Poziva modelu danas: 0")

        for stavka in (
            self.item_provider_google,
            self.item_provider_openai,
            self.item_provider_gemini_live,
            self.item_openai_long,
            text_model_menu,
            api_keys_menu,
            rumps.separator,
            self.item_debug,
            self.item_debug_open,
            self.item_tidy,
            self.item_polish_bullets,
            self.item_polish_para,
            self.item_polish_dedupe,
            rumps.separator,
            self.item_polish_count,
        ):
            ai_menu.add(stavka)
        for stavka in (self.item_tidy,
                       self.item_polish_para, self.item_polish_bullets,
                       self.item_polish_dedupe):
            stavka._menuitem.setIndentationLevel_(1)

        self.menu = [
            self.item_stop,
            self.settings_item,
        ]

        # Alati se sive dok je glavni prekidac ugasen. Lista parova, ne recnik:
        # rumps MenuItem nije hashable.
        self._polish_callbacks = [
            (self.item_tidy, self._toggle_tidy),
            (self.item_polish_para, self._make_polish_toggle("polish_paragraphs", True)),
            (self.item_polish_bullets, self._make_polish_toggle("polish_bullets", False)),
            (self.item_polish_dedupe, self._make_polish_toggle("polish_dedupe", False)),
        ]

        self._rebuild_mic_menu()
        self._attach_mic_delegate()
        self._rebuild_history_menu()
        self._sync_menu_marks()
        self._sync_stop_item()

    def _sync_stop_item(self):
        """Stavka postoji samo dok ima sta da se zaustavi."""
        item = getattr(self, "item_stop", None)
        ns = getattr(item, "_menuitem", None) if item is not None else None
        if ns is None:
            return
        # Bez katanca: _tick ide 20 puta u sekundi na glavnoj niti, a katanac
        # drzi i otvaranje mikrofona. Dva obicna citanja su ovde dovoljna.
        snima = self._recorder is not None or bool(self._starting)
        if ns.isHidden() == (not snima):
            return
        ns.setHidden_(not snima)

    def _stop_from_menu(self, _):
        self._on_stop()
        # Prekidac se vraca u mirovanje odmah: `_release_recorder` to radi tek
        # kad rep istekne, a dotle bi pritisak tastera radio STOP nad snimanjem
        # koje se vec zaustavlja.
        listener = getattr(self, "listener", None)
        if listener is not None:
            listener.reset()
        self._sync_stop_item()

    def refresh_mic_list(self):
        """Ponovo ucitaj uredjaje iz sistema pa prepravi podmeni."""
        audio.refresh_devices()
        self._rebuild_mic_menu()

    def _attach_mic_delegate(self):
        """Podmeni sam trazi osvezavanje kad se otvori."""
        menu = getattr(self.mic_menu, "_menu", None)
        if menu is None:
            return
        self._mic_delegate = _MicDelegate.alloc().initWithApp_(self)
        menu.setDelegate_(self._mic_delegate)

    def _rebuild_mic_menu(self):
        """Lista se pravi iznova jer se uredjaji prikljucuju i iskljucuju."""
        # rumps pravi NSMenu tek kad se doda prva stavka, pa clear() na jos
        # praznom podmeniju pada na None.removeAllItems().
        if getattr(self.mic_menu, "_menu", None) is not None:
            self.mic_menu.clear()
        self.mic_items = {}
        for name in [None] + audio.input_devices():
            label = "Sistemski podrazumevani" if name is None else name
            item = rumps.MenuItem(label, callback=self._make_mic_setter(name))
            self.mic_items[name] = item
            self.mic_menu.add(item)
        self._mark_mic()

    def _mark_mic(self):
        chosen = self.cfg.get("input_device")
        for name, item in getattr(self, "mic_items", {}).items():
            item.state = 1 if name == chosen else 0

    def _make_mic_setter(self, name):
        def setter(_):
            self.cfg["input_device"] = name
            config.save(self.cfg)
            self._mark_mic()
            self._keep_menu_open()

        return setter

    def _keep_menu_open(self):
        """Vrati meni posle klika.

        NSMenu se zatvara cim se stavka aktivira i to se javnim API-jem ne moze
        iskljuciti; jedini nacin je da se odmah otvori ponovo. Otvara se na
        prvom nivou, pa se u podmeni ulazi jos jednom.
        """
        nsapp = getattr(self, "_nsapp", None)
        item = getattr(nsapp, "nsstatusitem", None) if nsapp else None
        button = item.button() if item is not None else None
        if button is None:
            return
        button.performSelector_withObject_afterDelay_("performClick:", None, 0.05)

    def _sync_menu_marks(self):
        mode = self.cfg.get("mode", "hold")
        self.item_hold.state = 1 if mode == "hold" else 0
        self.item_toggle.state = 1 if mode == "toggle" else 0
        self.item_continuous.state = 1 if self.cfg.get("continuous", True) else 0
        self.item_recorded.title = (
            f"Ukupno snimljeno: {self._recorded_seconds():.0f} s"
        )

        stil = config.style(self.cfg)
        self.item_tidy.state = 1 if stil == "written" else 0
        self.item_ascii.state = 1 if self.cfg.get("ascii_diacritics", False) else 0
        self.item_abbrev.state = 1 if self.cfg.get("abbreviations", True) else 0
        self.item_lowercase.state = 1 if self.cfg.get("lowercase", True) else 0
        self.item_punctuation.state = 1 if self.cfg.get("strip_punctuation", True) else 0
        # Kvacica na „Pravilno" se izvodi iz ta cetiri, ne pamti se zasebno:
        # inace bi rucno gasenje jednog od njih ostavilo nad-prekidac da laze.
        self.item_pravilno.state = 1 if config.pravilno(self.cfg) else 0

        # Alati rade cim postoji kljuc; izabran alat je sam po sebi "ukljuceno".
        radi = polish.available(self.cfg)
        provider = self.cfg.get("transcription_provider", "google")
        self.item_provider_google.state = 1 if provider == "google" else 0
        self.item_provider_openai.state = 1 if provider == "openai" else 0
        self.item_provider_gemini_live.state = 1 if provider == "gemini_live" else 0
        self.item_openai_long.state = (
            1 if self.cfg.get("openai_long_recording", True) else 0
        )
        text_model = polish.text_model(self.cfg)
        self.item_text_model_gemini.state = 1 if text_model == "gemini" else 0
        self.item_text_model_groq.state = 1 if text_model == "groq" else 0
        self.item_gemini_key.title = (
            "Gemini API ključ: podešen" if self.cfg.get("polish_api_key")
            else "Gemini API ključ…"
        )
        self.item_openai_key.title = (
            "OpenAI API кључ: подешен" if self.cfg.get("openai_api_key")
            else "OpenAI API кључ…"
        )
        self.item_groq_key.title = (
            "Groq API ključ: podešen" if self.cfg.get("groq_api_key")
            else "Groq API ključ…"
        )
        self.item_debug.state = 1 if self.cfg.get("debug", False) else 0
        self.item_debug_open.set_callback(
            self._open_debug_log if self.cfg.get("debug", False) else None
        )
        self.item_polish_para.state = 1 if self.cfg.get("polish_paragraphs", True) else 0
        self.item_polish_bullets.state = 1 if self.cfg.get("polish_bullets", False) else 0
        self.item_polish_dedupe.state = 1 if self.cfg.get("polish_dedupe", False) else 0

        # Alat se ne bira dok je glavni prekidac ugasen. Sivi se skidanjem
        # callback-a, ne sa setEnabled_: NSMenu sam ukljucuje stavke koje imaju
        # akciju, pa bi setEnabled_ bio pregazen pri sledecem otvaranju menija.
        for stavka, cb in self._polish_callbacks:
            stavka.set_callback(cb if radi else None)
        self.item_polish_count.title = (
            f"Poziva modelu danas: {self._polish_today()}" if radi
            else "Nema API ključa (config.json)"
        )


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

    def _await_slot(self) -> bool:
        """Sacekaj da se mikrofon oslobodi.

        Posle pustanja tastera snimanje jos traje `tail_seconds`, pa bi pritisak
        odmah zatim bio tiho progutan — a bas tako se i koristi: stanes, pa
        odmah krenes ponovo dok se prethodni tekst jos obradjuje.
        """
        deadline = time.monotonic() + float(self.cfg.get("tail_seconds", 0.8)) + 0.7
        while True:
            with self._session_lock:
                if self._recorder is None:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.03)

    def _on_start(self):
        """Vraca False ako snimanje nije poceto — hotkey tada vrati svoje stanje."""
        self._live_off = False
        with self._session_lock:
            self._starting += 1
            self._stop_requested = False
        try:
            return self._start_recording()
        finally:
            with self._session_lock:
                self._starting -= 1

    def _start_recording(self):
        if not self._await_slot():
            return False
        with self._session_lock:
            if self._recorder is not None:
                return False
            # Lista uredjaja se osvezava pred svaki diktat (~2ms) — bez toga
            # PortAudio i dalje gleda uredjaje od pre vadjenja slusalica.
            audio.refresh_devices()
            recorder = audio.Recorder(
                sample_rate=self.cfg["sample_rate"],
                device=self.cfg.get("input_device"),
                max_seconds=self._limit_seconds(),
            )
            try:
                recorder.start()
            except Exception as exc:  # noqa: BLE001
                self.state.set(phase="error", message=f"Mikrofon: {exc}")
                return False
            recorder.session = self._nova_sesija(zakljucano=True)
            recorder.snimak = (
                rezerva.Snimak.novi(int(self.cfg["sample_rate"]))
                if self.cfg.get("rezervni_snimak", True) else None
            )
            self._recorder = recorder
            recorder.live_insert = (
                geministt.enabled(self.cfg)
                and bool(self.cfg.get("gemini_live_insert", False))
                and self.cfg.get("insert_method", "auto") != "clipboard_only"
            )
            self._record_started_at = time.monotonic()
            recorder.pokrenuto = self._record_started_at
            # Faza se upisuje pod katancem, da je _settle_phase prethodne
            # sesije ne prepise natrag na "obradjuje".
            self.state.set(phase="recording", message="")
            # STOP koji je stigao dok se mikrofon jos otvarao ne sme da propadne.
            propusteni_stop = self._stop_requested
            self._stop_requested = False

        if recorder.live_insert:
            # Živi delovi moraju da zauzmu mesto u istom redu kao ostali
            # diktati pre nego što prvi od njih stigne sa servera.
            recorder.ticket = self._next_ticket(recorder.session)
        threading.Thread(target=self._run_session, args=(recorder,), daemon=True).start()
        if propusteni_stop:
            self._on_stop()
        return True

    def _on_stop(self):
        with self._session_lock:
            recorder = self._recorder
            if recorder is None and self._starting:
                # Snimanje se jos otvara; zapamti STOP da ga pokretanje pokupi.
                self._stop_requested = True
                return
        if recorder is None:
            return
        self.state.set(phase="thinking")
        # Okvir sa prepisom nestaje odmah, ne kad rep istekne: snimanje je za
        # korisnika gotovo u trenutku kad pusti taster.
        self._live_off = True
        # Rep hvata poslednju rec — taster se pusta tacno na njenom kraju.
        rep = float(self.cfg.get("tail_seconds", 0.8))
        recorder.stop(tail=rep)
        cuvar = threading.Timer(rep + STOP_ROK, self._cuvar_zaustavljanja, args=(recorder,))
        cuvar.daemon = True
        cuvar.start()

    def _cuvar_zaustavljanja(self, recorder):
        """STOP mora da zaustavi sat, sta god da se zaglavilo iza njega.

        Posle odvajanja mikrofona od mreze (`_tracked`) ovo ne bi smelo da se
        desi. Ostaje kao osigurac: ako PortAudio zapne pri zatvaranju strima ili
        se pojavi neki treci uzrok, korisnik ne sme da gleda sat koji tece i
        taster koji ne reaguje. Linija u logu kaze da je osigurac radio, pa se
        uzrok trazi odatle.
        """
        with self._session_lock:
            if self._recorder is not recorder or recorder.released:
                return
            self._recorder = None
        print(f"[diktat] snimanje nije stalo {STOP_ROK:.0f}s posle STOP-a, "
              "oslobadjam mikrofon silom", flush=True)
        recorder._finish()
        listener = getattr(self, "listener", None)
        if listener is not None:
            listener.reset(pokrenuto=getattr(recorder, "pokrenuto", None))
        # Zatvaranje strima je upravo ono sto ume da zapne, pa ide u svoju nit.
        threading.Thread(target=self._release_recorder, args=(recorder,),
                         daemon=True).start()
        self._settle_phase()

    def _on_cancel(self, reason="otkazano"):
        with self._session_lock:
            recorder = self._recorder
            if recorder is None:
                return
            recorder.cancelled = True
        self._live_off = True
        recorder.stop()
        self._settle_phase(reason)

    def _limit_seconds(self) -> float:
        """Koliko sme da traje JEDAN pritisak tastera."""
        if geministt.enabled(self.cfg):
            # Live je jedini izvor koji salje zvuk DOK snimas (~2,5 MB/min), pa
            # zaboravljen diktat tu curi podatke sve vreme, a ne tek na kraju.
            # Zato kratka granica: posle nje se trazi nov pritisak.
            try:
                limit = int(self.cfg.get("gemini_live_max_seconds", 120))
            except (TypeError, ValueError):
                limit = 120
            return float(min(3600, max(30, limit)))
        if self.cfg.get("transcription_provider", "google") == "openai":
            if self._openai_long_recording():
                try:
                    limit = int(self.cfg.get("openai_max_seconds", 3600))
                except (TypeError, ValueError):
                    limit = 3600
                return float(min(3600, max(60, limit)))
            return float(self.cfg.get("max_request_seconds", 30))
        if self._segmenting():
            # Segmenti drze pojedinacne zahteve kratkim, pa granica sluzi samo
            # da zaboravljen diktat jednom stane.
            return float(self.cfg.get("continuous_max_seconds", 3600))
        return float(self.cfg.get("max_request_seconds", 30))

    def _segmenting(self) -> bool:
        return bool(self.cfg.get("continuous", True)) or bool(
            self.cfg.get("auto_segment", False)
        )

    def _nova_sesija(self, zakljucano=False) -> int:
        """Nov redni broj diktata. `zakljucano` znaci da katanac vec drzimo."""
        if zakljucano:
            self._session_seq += 1
            return self._session_seq
        with self._session_lock:
            self._session_seq += 1
            return self._session_seq

    def _next_ticket(self, session: int) -> int:
        """Redni broj za ubacivanje.

        Dodeljuje se u trenutku kad se AUDIO tog segmenta zavrsi, ne kad se
        prepoznavanje zavrsi. Posto mikrofon moze da snima samo jedno po jedno,
        taj redosled je uvek hronoloski — pa tekst stigne onako kako si govorio.
        """
        with self._count_lock:
            self._ticket += 1
            self._pending += 1
            self._pending_by[session] = self._pending_by.get(session, 0) + 1
            return self._ticket

    def _deliver(self, ticket: int, text: str, session: int):
        self._insert_q.put((ticket, text, session, False))

    def _deliver_live_part(self, ticket: int, text: str, session: int):
        if text.strip():
            self._insert_q.put((ticket, text, session, True))

    def _release_recorder(self, recorder):
        """Audio je gotov: pusti mikrofon ODMAH da moze sledeci diktat,
        dok prepoznavanje ovog jos traje u pozadini."""
        if recorder.released:
            return
        recorder.released = True
        # Strim se zatvara PRE oslobadjanja slota: sledeci diktat reinicijalizuje
        # PortAudio, a to ne sme da se desi dok je neki strim jos otvoren.
        # Ticket se uzima dok slot jos drzimo, da nova sesija ne preuzme nizi broj.
        recorder.close()
        if not recorder.ticket:
            recorder.ticket = self._next_ticket(recorder.session)
        with self._session_lock:
            if self._recorder is recorder:
                self._recorder = None
        # Prekidac se vraca u mirovanje: ako se snimanje samo prekinulo na
        # granici, sledeci pritisak mora da POKRENE, a ne da zaustavi. Ali samo
        # ako pritisak pripada OVOM snimanju; onaj koji je vec pokrenuo sledece
        # snimanje ostaje, inace to snimanje ne moze da se zaustavi tasterom.
        listener = getattr(self, "listener", None)
        if listener is not None:
            listener.reset(pokrenuto=getattr(recorder, "pokrenuto", None))
        if recorder.hit_limit:
            print(f"[diktat] granica od {self._limit_seconds():.0f}s — snimanje prekinuto")
        if recorder.captured == 0:
            # Strim se otvorio ali nije stigao nijedan sempl — uredjaj je
            # najverovatnije nestao pod nogama. Sledeci put krece iz cista.
            print("[diktat] nijedan sempl nije stigao, osvezavam audio uredjaje")
            audio.refresh_devices()

    def _settle_phase(self, message=""):
        """Ne gasi ekran ako je u medjuvremenu poceo nov diktat.

        Provera i upis idu pod istim katancem koji drzi i _on_start: inace se
        moze ubaciti izmedju, videti mikrofon jos slobodan, pa prepisati
        "snima" preko "obradjuje" iako je nov diktat vec poceo.
        """
        with self._session_lock:
            if self._recorder is not None:
                return
            with self._count_lock:
                busy = self._pending > 0
            if self._polishing:
                return                      # cekamo model, ne gasi prikaz
            self.state.set(phase="thinking" if busy else "idle", message=message)

    # --------------------------------------------------------- sesija

    def _tracked(self, recorder):
        """Mikrofon i mreza su odvojeni: zvuk cita zasebna nit.

        Ranije je mikrofon citao onaj ko salje na mrezu. Kad Gemini Live
        prestane da prima (izmereno 22.09.2026: „Isteklo vreme cekanja
        odgovora"), slanje stoji, pa niko ne cita mikrofon: snimanje se ne
        zavrsava, `_recorder` ostaje zauzet i taster deluje mrtav do isteka
        mreznog roka. Sada nit pumpe prazni mikrofon nezavisno od mreze, pise
        rezervnu kopiju i pusta mikrofon cim snimanje stane.
        """
        red: queue.Queue = queue.Queue()
        snimak = getattr(recorder, "snimak", None)

        def pumpa():
            try:
                for komad in recorder.chunks():
                    if snimak is not None:
                        snimak.upisi(komad)
                    red.put(komad)
            finally:
                if snimak is not None:
                    snimak.zatvori()
                self._release_recorder(recorder)
                red.put(None)

        threading.Thread(target=pumpa, name="diktat-mikrofon", daemon=True).start()
        try:
            while True:
                komad = red.get()
                if komad is None:
                    return
                yield komad
        finally:
            # Potrosac je odustao (pala mreza): mikrofon mora da stane i sam.
            recorder.stop()

    def _run_session(self, recorder):
        text = ""
        error = None
        try:
            text = self._transcribe(recorder)
        except Exception as exc:  # noqa: BLE001
            error = _short_error(exc)
            traceback.print_exc()
        finally:
            self._add_recorded_seconds(
                recorder.captured / 2 / float(self.cfg.get("sample_rate", 16000))
            )
            self._release_recorder(recorder)

        # Rezervni snimak ostaje samo kad prepis nije stigao; uspeo diktat ga
        # brise odmah, da glas ne stoji na disku bez razloga.
        snimak = getattr(recorder, "snimak", None)
        if snimak is not None and not recorder.cancelled and snimak.vrh < self.GOVOR_PEAK:
            # Bez govora nema sta da se prepise ni sacuva. Gemini Live na
            # tisinu ne vrati nista, pa bi to inace izaslo kao greska
            # „Isteklo vreme cekanja odgovora" i kao sacuvan snimak (izmereno
            # 22.09.2026: tri takva, vrh 0.002-0.022).
            if error:
                print(f"[diktat] bez govora, greska se ne prijavljuje: {error}")
            error = None
            text = ""
            snimak.obrisi()
        if snimak is not None and not error and (text or "").strip():
            snimak.obrisi()
        sacuvan = snimak is not None and snimak.putanja.exists()
        if sacuvan:
            self._sacuvani_dirty = True

        # Ticket dodeljen u _release_recorder mora da se preda tacno jednom,
        # inace red ubacivanja stane zauvek.
        ticket = recorder.ticket
        if recorder.cancelled or error:
            self._deliver(ticket, "", recorder.session)
            if error and not recorder.cancelled:
                if sacuvan:
                    error = f"{error[:120]} · snimak je sačuvan u Podešavanjima"
                self.state.set(phase="error", message=error)
            else:
                self._settle_phase()
            return

        if getattr(recorder, "live_insert", False):
            if text.strip():
                self._remember(text)
            self._deliver(ticket, "", recorder.session)
            return

        text = text.strip()
        if not text:
            self._deliver(ticket, "", recorder.session)
            self._settle_phase("(nista)")
            return

        text = self._finish(text)
        if not self._deferred():
            debug_session = self._debug_sessions.pop(recorder.session, None)
            if debug_session is not None:
                debug_session.final(text)
        self._deliver(ticket, text, recorder.session)

    def _finish(self, text: str) -> str:
        # Razmak na kraju je uvek: bez njega se recenice slepe pri nadovezivanju.
        return text + " "

    # Ispod ovog vrha amplitude nema govora: tiha soba je ~0.01, bucna ~0.08.
    # Prazan prepis tise od toga je stvarno tisina, ne izgubljen deo diktata.
    GOVOR_PEAK = 0.10
    GOVOR_SEKUNDI = 1.0

    def _bilo_je_govora(self, pcm: bytes) -> bool:
        """Gruba provera da snimak nije puka tisina."""
        return (
            self._seconds(pcm) >= self.GOVOR_SEKUNDI
            and audio.peak(pcm) >= self.GOVOR_PEAK
        )

    def _recognize_or_keep(self, pcm: bytes) -> str:
        """Prepis segmenta; prazan rezultat za jasan govor se samo prijavi.

        Ispis u logu je trag da deo diktata nije stigao. Zvuk celog diktata
        ostaje u rezervnom snimku (`rezerva.py`) dok prepis ne uspe.
        """
        text = self._recognize(pcm)
        if not text and self._bilo_je_govora(pcm):
            print(
                f"[diktat] prazan prepis za {self._seconds(pcm):.1f}s govora"
            )
        return text

    def _recognize(self, pcm: bytes) -> str:
        if not pcm:
            return ""
        seconds = self._seconds(pcm)
        if self.cfg.get("transcription_provider", "google") == "openai":
            return openai.post_process(openai.recognize(pcm, self.cfg), self.cfg)
        if geministt.enabled(self.cfg):
            return geministt.post_process(
                geministt.recognize(pcm, self.cfg), self.cfg
            )
        text, conf = webstt.recognize_full(
            pcm,
            language=self.cfg.get("language", "sr-RS"),
            sample_rate=self.cfg["sample_rate"],
            key=self.cfg.get("api_key") or None,
        )
        if not text:
            return text
        if self._formal() and polish.tidy_on(self.cfg):
            # Kad model sredjuje tekst, dobija ga kakav jeste:
            # skracenice i skidanje kvacica bi mu otezali citanje. Pravila se
            # tada primenjuju na kraju, nad ispravljenim tekstom.
            return text
        return self._apply_rules(text)

    def _write_ai_debug(self, session: int, trag: dict):
        """Upiši rezultate provajdera u log sesije ako je detaljan log uključen."""
        if not self._dump:
            return
        debug_session = self._debug_sessions.get(session)
        if debug_session is None:
            return
        debug_session.ai(
            trag.get("provider", "AI"),
            trag.get("google_text", ""),
            prompt=trag.get("prompt", ""),
            whisper_text=trag.get("whisper_text", ""),
            merged_text=trag.get("merged_text", ""),
            error=trag.get("error", ""),
            metadata=trag.get("metadata", ""),
        )

    def _apply_rules(self, text: str) -> str:
        """Nasa pravila nad jednim komadom teksta, bez prelamanja redova."""
        text = webstt.join_thousands(text)
        # Dve odluke su namerno nezavisne: moze se traziti samo mala slova,
        # samo uklanjanje znakova ili oba.
        text = self._apply_line_rules(text)
        text = self._skracenice(text)
        if self.cfg.get("ascii_diacritics", False):
            text = webstt.to_ascii(text)
        return text

    def _after_model(self, text: str) -> str:
        """Zavrsna podesavanja nad tekstom koji je model vec sredio.

        Lokalna prekidaca se primenjuju i posle modela, da ostanu nezavisna od
        toga da li je ukljuceno AI sredjivanje.
        """
        text = webstt.join_thousands(text)
        text = "\n".join(self._apply_line_rules(red) for red in text.split("\n"))
        text = self._skracenice(text)
        if self.cfg.get("ascii_diacritics", False):
            text = webstt.to_ascii(text)
        return text

    def _apply_line_rules(self, red: str) -> str:
        """Primeni lokalna pravila, ali sacuvaj oznaku bullet stavke."""
        oznaka = ""
        if red.startswith("- "):
            oznaka, red = "- ", red[2:]
        out = red
        if self.cfg.get("strip_punctuation", True):
            out = webstt.strip_punctuation(out)
        if self.cfg.get("lowercase", True):
            out = out.lower()
        else:
            # Pisani stil znaci i veliko slovo na pocetku recenice: model ga
            # ume propustiti, a granica ume da ostane i bez razmaka.
            out = webstt.capitalize_sentences(out)
        return oznaka + out

    def _skracenice(self, text: str) -> str:
        """Zamene koje korisnik sam definise; ista pravila kao na Androidu."""
        pravila = abbrev.parse(
            self.cfg.get("abbreviation_rules") or abbrev.default_text()
        ) if self.cfg.get("abbreviations", True) else []
        return abbrev.apply(
            text,
            pravila,
        )

    def _rules_over_paragraphs(self, text: str) -> str:
        """Ista pravila, ali PRELOM REDOVA prezivljava.

        `strip_punctuation` skuplja sve razmake u jedan, pa bi nad celim tekstom
        spojio i pasuse i tacke spiska u jedan red — a crtica, koja se tada
        nadje izmedju dva razmaka, i sama nestane. Zato red po red.
        """
        return "\n".join(self._apply_rules(red) for red in text.split("\n"))

    def _transcribe(self, recorder):
        """Na dugom diktatu sece snimak na pauzama i salje delove na obradu
        dok ti jos pricas — tako nema cekanja na kraju."""
        if self.cfg.get("transcription_provider", "google") == "openai":
            return self._transcribe_whole(recorder, "openai")
        if geministt.enabled(self.cfg):
            return self._transcribe_live(recorder)
        if not self._segmenting():
            session = self._dump.session() if self._dump else None
            if session is not None:
                self._debug_sessions[recorder.session] = session
            pcm = b"".join(self._tracked(recorder))
            if recorder.cancelled:
                return ""
            self._settle_phase()
            text = self._recognize_or_keep(pcm)
            if session is not None:
                session.segment(session.next_index(), pcm, text, kind="ceo")
                session.finish(pcm, text)
            return text

        detector = audio.PauseDetector(
            pause_seconds=float(self.cfg.get("pause_seconds", 0.7))
        )
        cut_after = float(self.cfg.get("segment_after_seconds", 15))
        hard_cut = float(self.cfg.get("max_request_seconds", 30))
        rate = self.cfg["sample_rate"]

        session = self._dump.session() if self._dump else None
        if session is not None:
            self._debug_sessions[recorder.session] = session
        everything: list[bytes] = []
        frames: list[bytes] = []
        seconds = 0.0

        for chunk in self._tracked(recorder):
            frames.append(chunk)
            if session is not None:
                everything.append(chunk)
            step = len(chunk) / 2 / rate
            # Duzina segmenta se meri PO ZVUKU, ne po zidnom satu. max_request_seconds
            # je granica koliko sekundi zvuka endpoint prima, pa ta dva moraju da
            # budu ista mera i onda kad potrosac kasni za mikrofonom.
            seconds += step
            # Nivo se racuna IZ OVOG komada. `recorder.level` je nivo poslednjeg
            # uhvacenog komada — detektor bi gledao jedan zvuk a sekao drugi.
            paused = detector.feed(audio.peak(chunk), step)
            # Tvrdi rez postoji jer endpoint puca na zahtevima duzim od ~30s,
            # a neko moze da prica bez ijedne pauze.
            if frames and ((paused and seconds >= cut_after) or seconds >= hard_cut):
                self._ship_segment(b"".join(frames), recorder.session, session)
                frames = []
                seconds = 0.0
                detector.reset()

        if recorder.cancelled:
            return ""
        self._settle_phase()
        tail = b"".join(frames)
        text = self._recognize_or_keep(tail)
        if not text and self._seconds(tail) > 0.4:
            print(f"[diktat] rep od {self._seconds(tail):.1f}s nije prepoznat")
        if session is not None:
            session.segment(session.next_index(), tail, text, kind="rep")
            session.finish(b"".join(everything), text)
        return text

    def _transcribe_whole(self, recorder, oznaka="ceo"):
        """Snimi CEO diktat u privremeni fajl i posalji ga tek posle Stop-a.

        Koriste ga izvori kojima se salje ceo diktat odjednom: OpenAI i Gemini
        Transcribe Live. Model tako vidi celinu umesto krhotina odsecenih na
        pauzama — isti razlog iz kog formalni rezim zove model jednom, na kraju.

        Privremeni disk sprecava da dugacak neprekidan diktat sve vreme raste u
        memoriji; sat vremena je preko 100 MB.
        """
        import tempfile

        session = self._dump.session() if self._dump else None
        if session is not None:
            self._debug_sessions[recorder.session] = session

        with tempfile.NamedTemporaryFile(prefix="diktat-ceo-", suffix=".pcm") as fh:
            for chunk in self._tracked(recorder):
                fh.write(chunk)
            fh.flush()
            fh.seek(0)
            pcm = fh.read()

        if recorder.cancelled:
            return ""
        self._settle_phase()
        text = self._recognize_or_keep(pcm)
        if session is not None:
            session.segment(session.next_index(), pcm, text, kind=oznaka)
            session.finish(pcm, text)
        return text

    def _transcribe_live(self, recorder):
        """Salji zvuk Live API-ju DOK korisnik jos prica.

        Zasto ne kao OpenAI, tek posle Stop-a: izmereno na 64.7s zvuka, slanje
        posle Stop-a ostavlja **15.6s** cekanja, a slanje u toku **0.0s** —
        server stize u realnom vremenu, pa je prepis gotov u trenutku kad
        pustis taster. Broj prepoznatih celina je isti (11).

        Cena je ista: naplacuje se zvuk, a zvuk je isti. Mana je sto se komadi
        sa mikrofona citaju samo jednom — drugi pokusaj nema sta da posalje, pa
        neuspeo Live diktat se ne ponavlja sam. Zato postoji rezervni snimak
        (`rezerva.py`), iz koga se prepis ponavlja rucno.
        """
        session = self._dump.session() if self._dump else None
        if session is not None:
            self._debug_sessions[recorder.session] = session

        komadi = self._tracked(recorder)
        # `on_update` nosi ceo tekst do tog trenutka (potvrđeno + međurezultat) i
        # ide SAMO u okvir na ekranu. U polje se kuca tek potvrđena celina
        # (`on_final`): međurezultat model sme da promeni, pa bi kasnija izmena
        # obrisala ručnu ispravku.
        prikaz = (
            (lambda tekst: self._live_preview(recorder, tekst))
            if self._live_preview_on() else None
        )
        sirovo = geministt.recognize_live_stream(
            # Kratak mrezni rok: zvuk ide u realnom vremenu, pa ni jedno slanje
            # ni citanje ne sme da visi minutima. Pre je bio 180 s.
            komadi, self.cfg, timeout=LIVE_MREZNI_ROK,
            on_update=prikaz,
            on_final=(
                (lambda raw: self._live_part(recorder, raw))
                if getattr(recorder, "live_insert", False) else None
            ),
        )

        if recorder.cancelled:
            return ""
        self._settle_phase()
        text = geministt.post_process(sirovo, self.cfg)
        if session is not None:
            session.segment(session.next_index(), b"", text, kind="gemini_live")
            session.finish(b"", text)
        return text

    def _live_preview_on(self) -> bool:
        return bool(self.cfg.get("live_preview", True))

    def _live_preview(self, recorder, tekst: str):
        """Radna nit samo ostavlja tekst; okvir crta `_tick` sa glavne niti."""
        if recorder.cancelled:
            return
        self._live_text = geministt.post_process(tekst, self.cfg).strip()
        self._live_text_dirty = True

    def _live_part(self, recorder, raw):
        if recorder.cancelled:
            return
        text = geministt.post_process(raw, self.cfg).strip()
        if text:
            self._deliver_live_part(recorder.ticket, text + " ", recorder.session)

    @staticmethod
    def _seconds(pcm: bytes, rate=16000) -> float:
        return len(pcm) / 2 / rate

    def _ship_segment(self, pcm: bytes, sesija: int, session=None):
        """Posalji odsecen deo na prepoznavanje, a snimanje ide dalje."""
        ticket = self._next_ticket(sesija)
        index = session.next_index() if session is not None else 0

        def work():
            text = ""
            try:
                text = self._recognize_or_keep(pcm)
                if not text:
                    # Ranije se ovo tiho gubilo — segment nestane bez traga.
                    print(f"[diktat] segment od {self._seconds(pcm):.1f}s nije prepoznat")
                if text:
                    text = self._finish(text)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                if session is not None:
                    session.segment(index, pcm, text)
                self._deliver(ticket, text, sesija)

        threading.Thread(target=work, daemon=True).start()

    def _insert_worker(self):
        """Lepi tekst strogo po redosledu snimanja.

        Prepoznavanja teku paralelno i mogu da se zavrse van reda — kratak
        drugi snimak lako stigne pre dugog prvog. Ovde se ceka na red.
        """
        buffered = {}
        expected = 1
        while True:
            seq, text, sesija, partial = self._insert_q.get()
            buffered.setdefault(seq, deque()).append((text, sesija, partial))
            while expected in buffered:
                events = buffered[expected]
                if not events:
                    break
                ready, cija, is_partial = events.popleft()
                if is_partial:
                    try:
                        insert.insert_live(ready)
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
                    continue
                del buffered[expected]
                expected += 1
                with self._count_lock:
                    if self._pending > 0:
                        self._pending -= 1
                    if self._pending_by.get(cija, 0) > 0:
                        self._pending_by[cija] -= 1
                if ready and self._deferred():
                    # Ceka se ceo diktat: model treba da vidi pun kontekst.
                    with self._formal_lock:
                        self._formal_parts.setdefault(cija, []).append(ready.strip())
                elif ready:
                    self._remember(ready)
                    try:
                        insert.insert(
                            ready,
                            method=self.cfg.get("insert_method", "auto"),
                            restore_clipboard=self.cfg.get("restore_clipboard", True),
                        )
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
            self._maybe_polish()
            self._settle_phase()

    def _polish_today(self) -> int:
        import datetime
        if self.cfg.get("polish_count_day") != datetime.date.today().isoformat():
            return 0
        return int(self.cfg.get("polish_count", 0))

    def _recorded_seconds(self) -> float:
        try:
            return max(0.0, float(self.cfg.get("recorded_seconds", 0.0)))
        except (TypeError, ValueError):
            return 0.0

    def _add_recorded_seconds(self, seconds: float):
        if seconds <= 0:
            return
        with self._stats_lock:
            self.cfg["recorded_seconds"] = self._recorded_seconds() + seconds
            config.save(self.cfg)

    def _count_polish(self, amount=1):
        """Brojač svih AI poziva po danu."""
        import datetime

        danas = datetime.date.today().isoformat()
        if self.cfg.get("polish_count_day") != danas:
            self.cfg["polish_count_day"] = danas
            self.cfg["polish_count"] = 0
        self.cfg["polish_count"] = int(self.cfg.get("polish_count", 0)) + amount
        config.save(self.cfg)
        # Naslov se osvezava odmah: _sync_menu_marks se zove samo na izmenu iz
        # menija, pa bi brojac inace stajao na staroj vrednosti do sledeceg klika.
        self.item_polish_count.title = f"Poziva modelu danas: {self._polish_today()}"

    def _maybe_polish(self):
        """Posalji modelu svaki diktat koji je u celini prepoznat.

        Gleda se SESIJA, a ne "da li mikrofon radi": nov diktat sme da pocne
        dok se prethodni obradjuje, pa bi cekanje na miran mikrofon spojilo dva
        diktata u jedan poziv i zalepilo ih zajedno.
        """
        if not self._deferred():
            return
        with self._session_lock:
            aktivna = self._recorder.session if self._recorder is not None else None
        for sesija in self._zavrsene(aktivna):
            with self._formal_lock:
                delovi = self._formal_parts.pop(sesija, [])
            tekst = " ".join(d for d in delovi if d).strip()
            if not tekst:
                continue
            with self._count_lock:
                self._polishing_count += 1
                self._polishing = True
            self.state.set(phase="polishing", message="")
            threading.Thread(
                target=self._do_polish, args=(sesija, tekst), daemon=True
            ).start()

    def _zavrsene(self, aktivna):
        """Sesije kojima je i zvuk i prepoznavanje gotovo."""
        with self._formal_lock:
            kandidati = list(self._formal_parts)
        with self._count_lock:
            return [
                s for s in kandidati
                if s != aktivna and self._pending_by.get(s, 0) == 0
            ]

    def _do_polish(self, sesija: int, tekst: str):
        # Tekst je cekao kraj diktata pa je jos sirov: ako model ne doteruje,
        # pravila moraju sada da odrade svoje.
        doteran = (
            self._doteraj(tekst, session=sesija) if self._formal()
            else self._rules_over_paragraphs(tekst)
        )
        with self._count_lock:
            self._polishing_count = max(0, self._polishing_count - 1)
            self._polishing = self._polishing_count > 0
        # Uz tacke ide nov red, a uz podelu na pasuse dva nova reda: sledeci
        # diktat tako ne moze da se zalepi za poslednji pasus.
        if self.cfg.get("polish_bullets", False):
            doteran = doteran.rstrip() + "\n"
        elif self._formal() and self.cfg.get("polish_paragraphs", True):
            doteran = doteran.rstrip() + "\n\n"
        else:
            doteran += " "
        debug_session = self._debug_sessions.pop(sesija, None)
        if debug_session is not None:
            debug_session.final(doteran)
        self._remember(doteran)
        try:
            insert.insert(
                doteran,
                method=self.cfg.get("insert_method", "auto"),
                restore_clipboard=self.cfg.get("restore_clipboard", True),
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        self._settle_phase()

    def _doteraj(self, tekst: str, vec_sredjeno=False, session=None) -> str:
        prompt = polish._uputstvo(self.cfg, vec_sredjeno) if self._dump else ""
        try:
            doteran = polish.polish(tekst, self.cfg, vec_sredjeno=vec_sredjeno)
            self._count_polish()
            if polish.tidy_on(self.cfg):
                # Uz sredjivanje ostaju samo podesavanja koja se sa njim ne
                # sudaraju — tekst je modelu isao nedirnut, pa bi inace izostala.
                doteran = self._after_model(doteran)
            else:
                # Kad sredjivanje nije trazeno, model ga svejedno uradi cim
                # prepisuje recenice — skracivanje ih vraca pravopisno uredne.
                # Uputstvo to ne resava pouzdano, pa presudjuju nasa pravila.
                doteran = self._rules_over_paragraphs(doteran)
            self._write_ai_debug(session, {
                "provider": f"{polish.text_model_label(self.cfg)} tekstualna obrada",
                "google_text": tekst,
                "prompt": prompt,
                "merged_text": doteran,
            })
            return doteran
        except Exception as exc:  # noqa: BLE001
            # Nedoteran tekst je bolji nego nikakav — model je dodatak, ne uslov.
            self._write_ai_debug(session, {
                "provider": f"{polish.text_model_label(self.cfg)} tekstualna obrada",
                "google_text": tekst,
                "prompt": prompt,
                "error": str(exc),
            })
            print(f"[diktat] doterivanje nije uspelo: {exc}")
            return tekst

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

        # Istoriju puni radna nit, a meni sme da se dira samo odavde.
        if self._history_dirty:
            self._history_dirty = False
            self._rebuild_history_menu()
        self.item_recorded.title = (
            f"Ukupno snimljeno: {self._recorded_seconds():.0f} s"
        )
        # Ide pre svih ranih izlaza iz _tick: stavka mora da se skloni i kad se
        # stanje ne menja (`dirty` je False), a meni sme da se dira samo odavde.
        self._sync_stop_item()
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

    def _tick_live_panel(self):
        """Okvir sa prepisom uživo; sve se crta sa glavne niti."""
        # Zaustavljeno snimanje gasi okvir odmah, u sledecem otkucaju (50ms).
        # Reader jos radi i sme da posalje jos koju celinu — one idu u polje,
        # ali se vise ne crtaju.
        if self._live_off or (self._recorder is None and not self._starting):
            self._live_text_dirty = False
            self._live_text = ""
            if self.live_panel.visible:
                self.live_panel.hide()
            return

        if not (self._live_preview_on() and geministt.enabled(self.cfg)):
            return
        # Okvir izlazi odmah, sa „Slušam…", a ne tek uz prvi tekst. Server
        # ponekad celoj sesiji ne pošalje nijedan međurezultat (izmereno: 2 od
        # 11 sesija, isti kod i isti snimak), pa bi prvi znak života inače bio
        # tek potvrđena celina na pauzi, u istom trenutku kad se tekst upiše.
        if self._live_text_dirty or not self.live_panel.visible:
            self._live_text_dirty = False
            self.live_panel.set_text(self._live_text)
            if not self.live_panel.visible:
                self.live_panel.show(self._live_text)

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

    def _open_settings(self, _):
        """Otvori desktop prozor sa istim grupama kao Android aplikacija."""
        if self._settings_window_ui is None:
            self._settings_window_ui = settings_window.SettingsWindow(self)
        self._settings_window_ui.show()
        # Svako otvaranje pita GitHub, ali ne cesce od jednom u minuti: dva
        # brza klika na ikonicu ne treba da budu dva zahteva.
        if (self.cfg.get("update_check", True) and not self._azur_radi
                and time.time() - self._azur_proveren_u > 60):
            self._azur_proveri(rucno=False)

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
            # tj. sva četiri pravila ugašena, uz pamćenje zatečenog izbora.
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
        self._sync_menu_marks()
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
        elif key == "mode":
            self.cfg["mode"] = "hold" if title == "Drži taster" else "toggle"
            if hasattr(self, "listener"):
                self.listener.mode = self.cfg["mode"]
        config.save(self.cfg)
        self._sync_menu_marks()
        if self._settings_window_ui is not None:
            self._settings_window_ui.refresh()

    def controlTextDidEndEditing_(self, notification):
        field = notification.object()
        key = str(field.identifier() or "")
        if key:
            self.cfg[key] = field.stringValue().strip()
            config.save(self.cfg)
            self._sync_menu_marks()

    def settingsButton_(self, sender):
        action = str(sender.identifier() or "")
        if action.startswith("copy_history_"):
            try:
                index = int(action.removeprefix("copy_history_"))
                with self._hist_lock:
                    value = self._history[index]
                insert.set_clipboard(value)
            except (ValueError, IndexError):
                pass
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

    def _remember(self, text: str):
        """Zapamti ubacen tekst. Zove se iz radne niti, pa meni ne dira —
        samo podigne zastavicu koju _tick pokupi na glavnoj niti."""
        clean = text.strip()
        if not clean:
            return
        # Istorija je namerno kratka da meni ostane pregledan. Stari config.json
        # Istorija je kratka, ali ista na desktopu i telefonu.
        size = max(1, min(int(self.cfg.get("history_size", 5)), 5))
        with self._hist_lock:
            if clean in self._history:
                self._history.remove(clean)
            self._history.insert(0, clean)
            del self._history[size:]
        config.save(self.cfg)
        self._history_dirty = True

    def _rebuild_history_menu(self):
        # rumps pravi NSMenu tek kad se doda prva stavka.
        if getattr(self.history_menu, "_menu", None) is not None:
            self.history_menu.clear()
        with self._hist_lock:
            stavke = list(self._history)
        if not stavke:
            prazno = rumps.MenuItem("(još ništa nije izdiktirano)")
            prazno.set_callback(None)
            self.history_menu.add(prazno)
            return
        for text in stavke:
            self.history_menu.add(
                rumps.MenuItem(_label(text), callback=self._make_copier(text))
            )
        self.history_menu.add(rumps.separator)
        self.history_menu.add(
            rumps.MenuItem("Obriši istoriju", callback=self._clear_history)
        )

    def _make_copier(self, text):
        def copier(_):
            insert.set_clipboard(text)

        return copier

    def _clear_history(self, _):
        with self._hist_lock:
            self._history.clear()
        self._rebuild_history_menu()

    def _set_hold(self, _):
        self._set_mode("hold")

    def _set_toggle(self, _):
        self._set_mode("toggle")

    def _toggle_pravilno(self, _):
        """Sva cetiri odjednom; gasenje vraca ono sto je bilo, ne podrazumevano."""
        config.postavi_pravilno(self.cfg, not config.pravilno(self.cfg))
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _toggle_local_text(self, key):
        self.cfg[key] = not bool(self.cfg.get(key, True))
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()







    # ------------------------------------------------------ rezervni snimci

    def _aktivni_snimci(self):
        snimak = getattr(self._recorder, "snimak", None)
        return [snimak.putanja] if snimak is not None else []

    def sacuvani_snimci(self):
        return rezerva.sacuvani(aktivni=self._aktivni_snimci())

    def _prepisi_sacuvan(self, index: int):
        if self._prepis_radi:
            return
        sacuvani = self.sacuvani_snimci()
        if index >= len(sacuvani):
            return
        sacuvan = sacuvani[index]
        self._prepis_radi = True
        self.prepis_status = "Prepisujem…"
        self._sacuvani_dirty = True
        self.state.set(phase="thinking", message="Prepisujem sačuvan snimak…")

        def worker():
            try:
                pcm, _rate = sacuvan.procitaj()
                tekst = self._prepisi_pcm(pcm).strip()
                if not tekst:
                    self.prepis_status = "U snimku nije prepoznat govor."
                    self.state.set(phase="idle", message="")
                    return
                insert.set_clipboard(tekst)
                self._remember(tekst)
                sacuvan.obrisi()
                self.state.set(phase="idle", message="")
                self.prepis_status = "Prepis je u clipboard-u i u istoriji. Nalepi ga sa ⌘V."
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self.prepis_status = f"Prepis nije uspeo: {_short_error(exc)}"
                self.state.set(phase="idle", message="")
            finally:
                self._prepis_radi = False
                self._sacuvani_dirty = True

        threading.Thread(target=worker, daemon=True).start()

    def _prepisi_pcm(self, pcm: bytes) -> str:
        """Ceo snimak kroz izabran servis, bez mikrofona.

        Google prima najvise ~30 s po zahtevu, pa se snimak sece na pauzama,
        isto kao u neprekidnom rezimu. Gemini i OpenAI primaju ceo snimak.
        """
        if (self.cfg.get("transcription_provider", "google") == "openai"
                or geministt.enabled(self.cfg)):
            return self._apply_rules(self._recognize(pcm))
        rate = int(self.cfg["sample_rate"])
        korak = rate // 10 * 2
        detektor = audio.PauseDetector(pause_seconds=float(self.cfg.get("pause_seconds", 0.7)))
        granica = float(self.cfg.get("max_request_seconds", 30))
        delovi, tekuci, sekundi = [], [], 0.0
        for i in range(0, len(pcm), korak):
            komad = pcm[i:i + korak]
            tekuci.append(komad)
            sekundi += len(komad) / 2 / rate
            pauza = detektor.feed(audio.peak(komad), len(komad) / 2 / rate)
            if (pauza and sekundi >= 15) or sekundi >= granica:
                delovi.append(self._recognize(b"".join(tekuci)))
                tekuci, sekundi = [], 0.0
                detektor.reset()
        if tekuci:
            delovi.append(self._recognize(b"".join(tekuci)))
        return " ".join(d.strip() for d in delovi if d and d.strip())

    # ---------------------------------------------------------- azuriranje

    def azur_dostupno(self) -> bool:
        izdanje = self._azur_izdanje
        return izdanje is not None and azuriranje.novije(
            azuriranje.trenutna_verzija(), izdanje.oznaka
        )

    def azur_dugme_stanje(self) -> tuple[str, bool]:
        """Natpis dugmeta u zaglavlju i da li je zeleno.

        Dugme nosi i trenutnu verziju, pa zasebna oznaka verzije ne postoji.
        Pun opis poslednjeg ishoda je u opisu dugmeta (tooltip).
        """
        trenutna = azuriranje.trenutna_verzija() or "?"
        if self._azur_radi:
            return self._azur_status or "Sačekaj…", False
        if self.azur_dostupno():
            return f"Ažuriraj {trenutna} → {self._azur_izdanje.oznaka}", True
        if self._azur_ishod:
            return f"{self._azur_ishod} ({trenutna})", False
        return f"Proveri ažuriranje ({trenutna})", False

    def _tick_azuriranje(self):
        if self._azur_restart and self._recorder is None and not self._starting:
            with self._count_lock:
                pending = self._pending
            if pending == 0:
                self._azur_restart = False
                print(f"[diktat] azurirano na {azuriranje.trenutna_verzija() or '?'}"
                      ", ponovo pokrecem", flush=True)
                try:
                    self.listener.stop()
                finally:
                    azuriranje.ponovo_pokreni()
        if (self.cfg.get("update_check", True) and not self._azur_radi
                and time.time() - self._azur_proveren_u > azuriranje.RAZMAK_PROVERE):
            self._azur_proveri(rucno=False)

    def _azur_proveri(self, rucno: bool):
        self._azur_radi = True
        self._azur_proveren_u = time.time()
        if rucno:
            self._azur_status = "Proveravam…"
            self._azur_ishod = ""
        self._azur_dirty = True

        def worker():
            try:
                izdanje = azuriranje.poslednje()
                self._azur_izdanje = izdanje
                trenutna = azuriranje.trenutna_verzija()
                if azuriranje.novije(trenutna, izdanje.oznaka):
                    self._azur_status = f"Dostupna je nova verzija {izdanje.oznaka}."
                else:
                    self._azur_status = f"Imaš najnoviju verziju ({trenutna})."
                    if rucno:
                        self._azur_ishod = "Najnovija verzija"
            except Exception as exc:  # noqa: BLE001
                # Tiha provera bez mreze ne sme da prepise poslednji dobar ishod.
                if rucno or not self._azur_status:
                    self._azur_status = f"Provera nije uspela: {_short_error(exc)}"
                if rucno:
                    self._azur_ishod = "Provera nije uspela"
            finally:
                self._azur_radi = False
                self._azur_dirty = True

        threading.Thread(target=worker, daemon=True).start()

    def _azur_klik(self):
        if self._azur_radi:
            return
        if not self.azur_dostupno():
            self._azur_proveri(rucno=True)
            return
        if self._recorder is not None or self._starting:
            self._azur_status = "Sačekaj da se diktat završi, pa klikni ponovo."
            self._azur_ishod = "Sačekaj kraj diktata"
            self._azur_dirty = True
            return
        izdanje = self._azur_izdanje
        self._azur_radi = True
        self._azur_dirty = True

        def javi(poruka):
            self._azur_status = poruka
            self._azur_dirty = True

        def worker():
            try:
                azuriranje.instaliraj(izdanje, javi=javi)
                javi("Ponovo pokrećem…")
                self._azur_restart = True
            except Exception as exc:  # noqa: BLE001
                javi(f"Ažuriranje nije uspelo: {_short_error(exc)}")
                self._azur_ishod = "Ažuriranje nije uspelo"
            finally:
                self._azur_radi = False
                self._azur_dirty = True

        threading.Thread(target=worker, daemon=True).start()

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

    def _set_transcription_provider(self, provider):
        self.cfg["transcription_provider"] = (
            provider if provider in config.PROVIDERS else "google"
        )
        if self.cfg["transcription_provider"] == "openai":
            self.cfg["openai_output_script"] = "latin"
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _openai_long_recording(self) -> bool:
        return (
            self.cfg.get("transcription_provider", "google") == "openai"
            and bool(self.cfg.get("openai_long_recording", True))
        )

    def _toggle_openai_long(self, _):
        self.cfg["openai_long_recording"] = not bool(
            self.cfg.get("openai_long_recording", True)
        )
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _set_text_model(self, model):
        self.cfg["text_model"] = "groq" if model == "groq" else "gemini"
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _set_gemini_key(self, _):
        odgovor = rumps.Window(
            message=(
                "Ključ se čuva samo u lokalnom config.json fajlu. "
                "Koristi se za Gemini obradu teksta i proveru snimka."
            ),
            title="Gemini API ključ",
            default_text=self.cfg.get("polish_api_key", ""),
            ok="Sačuvaj",
            cancel="Otkaži",
            dimensions=(420, 24),
        ).run()
        if not odgovor.clicked:
            return
        self.cfg["polish_api_key"] = odgovor.text.strip()
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _set_openai_key(self, _):
        odgovor = rumps.Window(
            message=(
                "Кључ се чува само у локалном config.json фајлу. "
                "За транскрипцију се користи OpenAI API модел gpt-transcribe."
            ),
            title="OpenAI API кључ",
            default_text=self.cfg.get("openai_api_key", ""),
            ok="Сачувај",
            cancel="Откажи",
            dimensions=(420, 24),
        ).run()
        if not odgovor.clicked:
            return
        self.cfg["openai_api_key"] = odgovor.text.strip()
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _set_groq_key(self, _):
        odgovor = rumps.Window(
            message="Ključ se čuva samo u lokalnom config.json fajlu.",
            title="Groq API ključ",
            default_text=self.cfg.get("groq_api_key", ""),
            ok="Sačuvaj",
            cancel="Otkaži",
            dimensions=(420, 24),
        ).run()
        if not odgovor.clicked:
            return
        self.cfg["groq_api_key"] = odgovor.text.strip()
        config.save(self.cfg)
        self._sync_menu_marks()

    def _deferred(self) -> bool:
        """Ceka li se kraj diktata zbog modela."""
        return self._formal()

    def _formal(self) -> bool:
        """Ceka li se ceo diktat zbog modela.

        Bez ijednog izabranog alata nema sta da se posalje, pa se tekst lepi
        odmah — inace bi diktat visio na praznom pozivu.
        """
        return polish.available(self.cfg) and bool(polish.tools(self.cfg))

    def _toggle_tidy(self, _):
        """Sredjivanje radi model, pa bez ukljucenog AI-ja nema ko da ga izvrsi."""
        sredjeno = config.style(self.cfg) != "written"
        self.cfg["text_style"] = "written" if sredjeno else "spoken"
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _make_polish_toggle(self, key, default):
        def toggle(_):
            self.cfg[key] = not bool(self.cfg.get(key, default))
            config.save(self.cfg)
            self._sync_menu_marks()
            self._keep_menu_open()
        return toggle

    def _toggle_continuous(self, _):
        self.cfg["continuous"] = not bool(self.cfg.get("continuous", True))
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _set_mode(self, mode):
        self.cfg["mode"] = mode
        config.save(self.cfg)
        self.listener.mode = mode
        self._sync_menu_marks()
        self._keep_menu_open()

    def _toggle_ascii(self, _):
        self.cfg["ascii_diacritics"] = not bool(
            self.cfg.get("ascii_diacritics", False)
        )
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _apply_debug(self, on):
        self._dump = (
            debugdump.DebugDump(
                self.cfg.get("debug_dir", "~/Diktat-debug"), self.cfg["sample_rate"]
            )
            if on
            else None
        )

    def _toggle_debug(self, _):
        self.cfg["debug"] = not bool(self.cfg.get("debug", False))
        config.save(self.cfg)
        self._apply_debug(self.cfg["debug"])
        self._sync_menu_marks()
        self._keep_menu_open()

    def _open_debug_log(self, _):
        if not self._dump:
            return
        # `open` otvara poslednji .txt ako postoji, a folder ako još nema loga.
        subprocess.Popen(["open", str(self._dump.latest_log())])

    def _quit(self, _):
        try:
            self.listener.stop()
        finally:
            rumps.quit_application()

    # ------------------------------------------------------------- run

    def run(self, **kw):
        self.listener.start()
        super().run(**kw)


def _label(text: str, limit=52) -> str:
    jedan_red = " ".join(text.split())
    return jedan_red if len(jedan_red) <= limit else jedan_red[: limit - 1] + "…"


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return text[0][:200] if text else exc.__class__.__name__


def main():
    DictateApp().run()
