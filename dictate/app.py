"""Menu-bar aplikacija: drzi desni Command -> diktat -> tekst u aktivnu aplikaciju.

Niti:
  glavna       — rumps / AppKit petlja + Timer koji na 20 Hz osvezava ikonicu i HUD
  pynput       — event tap za hotkey
  sesija       — snimanje + gRPC stream ka Google-u (jedna po diktatu)

AppKit se dira iskljucivo iz glavne niti; radne niti samo upisuju u `State`.
"""

import queue
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
    abbrev, audio, config, debugdump, hotkey, insert, listen, overlay, pending,
    polish, groq, webstt,
)

# Dok snima, naslov je proteklo vreme u sekundama ("07") umesto ikonice.
ICON = {
    "idle": "00",
    "error": "⚠️",
}
RED_AFTER = 15.0   # od ove sekunde cifre snimanja postaju crvene

# Naranđasta umesto ciste zute: zuta je na svetlom menu baru jedva citljiva.
TITLE_COLORS = {
    "recording": AppKit.NSColor.systemRedColor,
    "busy": AppKit.NSColor.systemOrangeColor,
    "polishing": AppKit.NSColor.systemBlueColor,
}

ERROR_HUD_SECONDS = 4.0


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

        self._client_error = None
        self._session_lock = threading.Lock()
        self._recorder = None
        self._policy_set = False
        self._error_shown_at = None
        self._record_started_at = 0.0
        self._last_clock = ""
        self._menubar = (None, None)
        self._count_lock = threading.Lock()
        self._pending = 0        # snimci koji se prepoznaju
        self._ticket = 0         # redni broj segmenta za ubacivanje
        self._insert_q: queue.Queue = queue.Queue()
        self._dump = None
        self._debug_sessions = {}
        self._pending_store = pending.PendingStore(
            self.cfg.get("pending_dir", "~/Diktat-neuspeli"),
            self.cfg["sample_rate"],
        )
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
        self._audio_lock = threading.Lock()
        self._audio_parts: dict[int, dict[int, bytes]] = {}
        self._audio_seconds: dict[int, float] = {}
        self._polishing = False
        self._polishing_count = 0

        self._build_menu()
        self._apply_debug(self.cfg.get("debug", False))
        self._preflight()
        threading.Thread(target=self._insert_worker, daemon=True).start()

        self.listener = hotkey.HotkeyListener(
            self.cfg,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_cancel=self._on_cancel,
            is_synthetic=insert.injecting,
        )

    # ------------------------------------------------------------------ UI

    def _build_menu(self):
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
        for stavka in (self.item_hold, self.item_toggle, None, self.item_continuous):
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
        for stavka in (self.item_ascii, self.item_abbrev):
            tekst_menu.add(stavka)

        # Sve sto model radi je na jednom mestu, ali u dva bloka: prepoznavanje
        # (sporo, salje zvuk) i obrada teksta (brzo, salje samo tekst).
        # Nema glavnog prekidaca: izabran alat sam po sebi znaci da se AI
        # koristi. Prekidac je bio jos jedan korak koji nista nije odlucivao.
        ai_menu = rumps.MenuItem("AI")
        self.item_listen = rumps.MenuItem(
            "Google/Gemini sluša snimak", callback=self._toggle_listen
        )
        self.item_groq = rumps.MenuItem(
            "Groq preciznost (Whisper + GPT-OSS)", callback=self._toggle_groq
        )
        self.item_groq_key = rumps.MenuItem(
            "Groq API ključ…", callback=self._set_groq_key
        )
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
        self.item_language_out = rumps.MenuItem(
            "Jezik izlaza…", callback=self._set_output_language
        )

        for stavka in (
            self.item_listen,
            self.item_groq,
            self.item_groq_key,
            self.item_debug,
            self.item_debug_open,
            self.item_tidy,
            self.item_polish_bullets,
            self.item_polish_para,
            self.item_polish_dedupe,
            self.item_language_out,
            rumps.separator,
            self.item_polish_count,
        ):
            ai_menu.add(stavka)
        for stavka in (self.item_listen, self.item_tidy,
                       self.item_polish_para, self.item_polish_bullets,
                       self.item_polish_dedupe, self.item_language_out):
            stavka._menuitem.setIndentationLevel_(1)

        self.menu = [
            self.history_menu,
            None,
            self.mic_menu,
            snimanje_menu,
            ai_menu,
            tekst_menu,
            None,
            rumps.MenuItem("Izlaz", callback=self._quit),
        ]

        # Alati se sive dok je glavni prekidac ugasen. Lista parova, ne recnik:
        # rumps MenuItem nije hashable.
        self._polish_callbacks = [
            (self.item_listen, self._toggle_listen),
            (self.item_tidy, self._toggle_tidy),
            (self.item_polish_para, self._make_polish_toggle("polish_paragraphs", True)),
            (self.item_polish_bullets, self._make_polish_toggle("polish_bullets", False)),
            (self.item_polish_dedupe, self._make_polish_toggle("polish_dedupe", False)),
            (self.item_language_out, self._set_output_language),
        ]

        self._rebuild_mic_menu()
        self._attach_mic_delegate()
        self._rebuild_history_menu()
        self._sync_menu_marks()

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

        stil = config.style(self.cfg)
        self.item_tidy.state = 1 if stil == "written" else 0
        self.item_ascii.state = 1 if self.cfg.get("ascii_diacritics", False) else 0
        self.item_abbrev.state = 1 if self.cfg.get("abbreviations", True) else 0

        # Alati rade cim postoji kljuc; izabran alat je sam po sebi "ukljuceno".
        radi = polish.available(self.cfg)
        self.item_listen.state = 1 if listen.enabled(self.cfg) else 0
        self.item_groq.state = 1 if groq.enabled(self.cfg) else 0
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
        jezik = polish.output_language(self.cfg)
        self.item_language_out.title = f"Jezik izlaza: {jezik}" if jezik else "Jezik izlaza…"
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
            self._recorder = recorder
            self._record_started_at = time.monotonic()
            # Faza se upisuje pod katancem, da je _settle_phase prethodne
            # sesije ne prepise natrag na "obradjuje".
            self.state.set(phase="recording", message="")

        threading.Thread(target=self._run_session, args=(recorder,), daemon=True).start()
        return True

    def _on_stop(self):
        with self._session_lock:
            recorder = self._recorder
        if recorder is None:
            return
        self.state.set(phase="thinking")
        # Rep hvata poslednju rec — taster se pusta tacno na njenom kraju.
        recorder.stop(tail=float(self.cfg.get("tail_seconds", 0.8)))

    def _on_cancel(self, reason="otkazano"):
        with self._session_lock:
            recorder = self._recorder
            if recorder is None:
                return
            recorder.cancelled = True
        recorder.stop()
        self._settle_phase(reason)

    def _limit_seconds(self) -> float:
        """Koliko sme da traje JEDAN pritisak tastera."""
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
        self._insert_q.put((ticket, text, session))

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
        recorder.ticket = self._next_ticket(recorder.session)
        with self._session_lock:
            if self._recorder is recorder:
                self._recorder = None
        # Prekidac se vraca u mirovanje: ako se snimanje samo prekinulo na
        # granici, sledeci pritisak mora da POKRENE, a ne da zaustavi.
        listener = getattr(self, "listener", None)
        if listener is not None:
            listener.reset()
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
        """Omotac oko chunks() koji pusta mikrofon cim audio stane."""
        try:
            yield from recorder.chunks()
        finally:
            self._release_recorder(recorder)

    def _run_session(self, recorder):
        text = ""
        error = None
        try:
            text = self._transcribe(recorder)
        except Exception as exc:  # noqa: BLE001
            error = _short_error(exc)
            traceback.print_exc()
        finally:
            self._release_recorder(recorder)

        # Ticket dodeljen u _release_recorder mora da se preda tacno jednom,
        # inace red ubacivanja stane zauvek.
        ticket = recorder.ticket
        if recorder.cancelled or error:
            self._deliver(ticket, "", recorder.session)
            if error and not recorder.cancelled:
                self.state.set(phase="error", message=error)
            else:
                self._settle_phase()
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

    def _recognize_or_keep(self, pcm: bytes) -> str:
        """Ako prepoznavanje padne, snimak ide na disk pa moze da se ponovi."""
        try:
            return self._recognize(pcm)
        except Exception:
            saved = self._pending_store.save(pcm)
            if saved is not None:
                print(f"[diktat] snimak sacuvan za ponovni pokusaj: {saved}")
                self._history_dirty = True
            raise

    def _recognize(self, pcm: bytes) -> str:
        if not pcm:
            return ""
        text, conf = webstt.recognize_full(
            pcm,
            language=self.cfg.get("language", "sr-RS"),
            sample_rate=self.cfg["sample_rate"],
            key=self.cfg.get("api_key") or None,
        )
        if not text:
            return text
        if self._batch() or (self._formal() and polish.tidy_on(self.cfg)):
            # Kad model sredjuje tekst ili slusa snimak, dobija ga kakav jeste:
            # skracenice i skidanje kvacica bi mu otezali citanje. Pravila se
            # tada primenjuju na kraju, nad ispravljenim tekstom.
            return text
        return self._apply_rules(text)

    def _keep_audio(self, session: int, ticket: int, pcm: bytes):
        """Sacuvaj zvuk segmenta za grupnu proveru na kraju diktata.

        Ceo diktat ide modelu jednim pozivom: provera po segmentu je trosila
        6-9 poziva na jednu diktiranu poruku, a model je video krhotinu umesto
        celine. Granica postoji jer neprekidan rezim ume da traje satima —
        preko nje se zvuk vise ne cuva, a tekst ostaje onakav kakav je.
        """
        if not pcm or not (listen.enabled(self.cfg) or groq.enabled(self.cfg)):
            return
        granica = float(self.cfg.get("audio_check_max_seconds", 120))
        with self._audio_lock:
            if self._audio_seconds.get(session, 0.0) + self._seconds(pcm) > granica:
                return
            self._audio_parts.setdefault(session, {})[ticket] = pcm
            self._audio_seconds[session] = (
                self._audio_seconds.get(session, 0.0) + self._seconds(pcm)
            )

    def _take_audio(self, session: int):
        """Zvuk jednog diktata, hronoloski."""
        with self._audio_lock:
            delovi = self._audio_parts.pop(session, {})
            self._audio_seconds.pop(session, None)
        rate = self.cfg["sample_rate"]
        return [(delovi[k], rate) for k in sorted(delovi)]

    def _slusaj(self, session: int, tekst: str):
        """Drugo misljenje o celom diktatu; na otkaz ostaje prvi prepis.

        Vraca (tekst, da li je model zaista slusao) — ako jeste, tekst vec ima
        interpunkciju i kvacice, pa sledeci poziv nema sta da sredjuje.
        """
        delovi = self._take_audio(session)
        if not delovi:
            return tekst, False
        trag = {
            "provider": "Gemini audio check",
            "google_text": tekst,
            "metadata": f"audio: {len(delovi)} segment(a); Gemini model: {self.cfg.get('polish_model') or polish.DEFAULT_MODEL}",
        }
        try:
            if groq.enabled(self.cfg):
                # Groq dobija prednost kada je uključen: u suprotnom bi isti
                # audio nepotrebno išao i Gemini-ju i Groq-u.
                ispravljen = groq.check_batch(delovi, tekst, self.cfg, trace=trag)
                self._count_polish(2)  # Whisper + GPT-OSS
            else:
                ispravljen = listen.check_batch(delovi, tekst, self.cfg)
                self._count_polish()
                trag["prompt"] = listen._uputstvo(tekst, self.cfg, len(delovi))
            trag["merged_text"] = ispravljen
            self._write_ai_debug(session, trag)
            if ispravljen != tekst:
                print(f"[diktat] AI slušao {len(delovi)} segm.: {tekst!r} -> {ispravljen!r}")
            return ispravljen, True
        except Exception as exc:  # noqa: BLE001
            trag["error"] = str(exc)
            self._write_ai_debug(session, trag)
            print(f"[diktat] provera snimka nije uspela: {exc}")
            return tekst, False

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
        # „Kako sam izgovorio" znaci mala slova i bez interpunkcije; „sirovo"
        # ostavlja ono sto Google vrati. „Pravopisno sredjeno" ovde nema sta da
        # radi — to je posao modela, pa tekst prolazi nedirnut.
        izgovoreno = config.style(self.cfg) == "spoken"
        if izgovoreno:
            text = webstt.strip_punctuation(text)
            text = text.lower()
        text = self._skracenice(text)
        if self.cfg.get("ascii_diacritics", False):
            text = webstt.to_ascii(text)
        return text

    def _after_model(self, text: str) -> str:
        """Zavrsna podesavanja nad tekstom koji je model vec sredio.

        Mala slova i brisanje interpunkcije se ovde NE primenjuju: to je bas
        posao koji je model dobio, pa bi jedno gasilo drugo. Ostaje ono sto se
        sa njegovim oblikovanjem ne sudara.
        """
        text = webstt.join_thousands(text)
        text = self._skracenice(text)
        if self.cfg.get("ascii_diacritics", False):
            text = webstt.to_ascii(text)
        return text

    def _skracenice(self, text: str) -> str:
        """Zamene koje korisnik sam definise; ista pravila kao na Androidu."""
        if not self.cfg.get("abbreviations", True):
            return text
        pravila = abbrev.parse(
            self.cfg.get("abbreviation_rules") or abbrev.default_text()
        )
        return abbrev.apply(text, pravila)

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
        if not self._segmenting():
            session = self._dump.session() if self._dump else None
            if session is not None:
                self._debug_sessions[recorder.session] = session
            pcm = b"".join(self._tracked(recorder))
            if recorder.cancelled:
                return ""
            self._settle_phase()
            self._keep_audio(recorder.session, recorder.ticket, pcm)
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
        self._keep_audio(recorder.session, recorder.ticket, tail)
        text = self._recognize_or_keep(tail)
        if not text and self._seconds(tail) > 0.4:
            print(f"[diktat] rep od {self._seconds(tail):.1f}s nije prepoznat")
        if session is not None:
            session.segment(session.next_index(), tail, text, kind="rep")
            session.finish(b"".join(everything), text)
        return text

    @staticmethod
    def _seconds(pcm: bytes, rate=16000) -> float:
        return len(pcm) / 2 / rate

    def _ship_segment(self, pcm: bytes, sesija: int, session=None):
        """Posalji odsecen deo na prepoznavanje, a snimanje ide dalje."""
        ticket = self._next_ticket(sesija)
        self._keep_audio(sesija, ticket, pcm)
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
            seq, text, sesija = self._insert_q.get()
            buffered[seq] = (text, sesija)
            while expected in buffered:
                ready, cija = buffered.pop(expected)
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
                # Otkazan ili prazan diktat: zvuk mora da ode, inace bi usao u
                # sledecu proveru i model bi "cuo" prosli diktat.
                self._take_audio(sesija)
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
        sredjeno = False
        if self._batch():
            tekst, sredjeno = self._slusaj(sesija, tekst)
        # Tekst je cekao kraj diktata pa je jos sirov: ako model ne doteruje,
        # pravila moraju sada da odrade svoje.
        doteran = (
            self._doteraj(tekst, sredjeno, sesija) if self._formal()
            else self._rules_over_paragraphs(tekst)
        )
        with self._count_lock:
            self._polishing_count = max(0, self._polishing_count - 1)
            self._polishing = self._polishing_count > 0
        # Uz tacke ide nov red umesto razmaka: sledeci diktat tako pocinje svoju
        # tacku umesto da se nastavi na prethodnu.
        doteran = doteran.rstrip() + "\n" if self.cfg.get("polish_bullets", False) else doteran + " "
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
                "provider": "Gemini tekstualna obrada",
                "google_text": tekst,
                "prompt": prompt,
                "merged_text": doteran,
            })
            return doteran
        except Exception as exc:  # noqa: BLE001
            # Nedoteran tekst je bolji nego nikakav — model je dodatak, ne uslov.
            self._write_ai_debug(session, {
                "provider": "Gemini tekstualna obrada",
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

        # Istoriju puni radna nit, a meni sme da se dira samo odavde.
        if self._history_dirty:
            self._history_dirty = False
            self._rebuild_history_menu()

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

        if not dirty:
            return

        # U naslovu su UVEK cifre; stanje se vidi po boji. Tekst umesto brojeva
        # je gutao sat, pa se nije videlo koliko traje ni koliko je ostalo.
        if phase == "polishing":
            self._set_menubar(self._last_clock or ICON["idle"], "polishing")
        elif phase == "thinking":
            self._set_menubar(self._last_clock or ICON["idle"], "busy")
        else:
            self._set_menubar(ICON.get(phase, ICON["idle"]))

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
        if self._segmenting():
            # Nema granice od 30s, pa crveno upozorenje nema sta da najavi.
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

    def _remember(self, text: str):
        """Zapamti ubacen tekst. Zove se iz radne niti, pa meni ne dira —
        samo podigne zastavicu koju _tick pokupi na glavnoj niti."""
        clean = text.strip()
        if not clean:
            return
        size = max(1, int(self.cfg.get("history_size", 10)))
        with self._hist_lock:
            if clean in self._history:
                self._history.remove(clean)
            self._history.insert(0, clean)
            del self._history[size:]
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

    def _toggle_listen(self, _):
        if not polish.available(self.cfg):
            self.state.set(phase="error", message="Upiši polish_api_key u config.json")
            return
        self.cfg["audio_check"] = not bool(self.cfg.get("audio_check", False))
        config.save(self.cfg)
        self._sync_menu_marks()
        self._keep_menu_open()

    def _toggle_groq(self, _):
        if not self.cfg.get("groq_api_key"):
            self._set_groq_key(_)
            if not self.cfg.get("groq_api_key"):
                return
        self.cfg["groq_enabled"] = not bool(self.cfg.get("groq_enabled", False))
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

    def _batch(self) -> bool:
        """Ceka li se kraj diktata zbog provere snimka."""
        return listen.enabled(self.cfg) or groq.enabled(self.cfg)

    def _deferred(self) -> bool:
        """Ceka li se kraj diktata uopste — zbog modela ili zbog provere."""
        return self._formal() or self._batch()

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

    def _set_output_language(self, _):
        """Slobodan opis, ne spisak: „pola makedonski pola srpski" je isto vazeci."""
        odgovor = rumps.Window(
            message="Na kom jeziku tekst treba da izađe?\nPrazno = bez prevoda.",
            title="Jezik izlaza",
            default_text=polish.output_language(self.cfg),
            ok="Sačuvaj",
            cancel="Otkaži",
            dimensions=(260, 24),
        ).run()
        if not odgovor.clicked:
            return
        self.cfg["output_language"] = odgovor.text.strip()
        config.save(self.cfg)
        self._sync_menu_marks()

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
