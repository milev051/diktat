"""Menu-bar aplikacija: drzi desni Command -> diktat -> tekst u aktivnu aplikaciju.

Niti:
  glavna       — rumps / AppKit petlja + Timer koji na 20 Hz osvezava ikonicu i HUD
  pynput       — event tap za hotkey
  sesija       — snimanje + gRPC stream ka Google-u (jedna po diktatu)

AppKit se dira iskljucivo iz glavne niti; radne niti samo upisuju u `State`.
"""

import math
import queue
import threading
import time
import traceback

import AppKit
import rumps

from . import audio, config, hotkey, insert, overlay, stt, webstt

ICON = {
    "idle": "🎙",
    "recording": "🔴",
    "thinking": "✳️",
    "error": "⚠️",
}

HUD_MAX_CHARS = 90
ERROR_HUD_SECONDS = 4.0
METER_BLOCKS = "▁▂▃▄▅▆▇█▇▆▅▄"
WARN_SECONDS = 10.0   # kad se predje u odbrojavanje

_WEB = object()   # oznaka da je motor "web" (nema klijenta za pravljenje)


class State:
    """Deljeno stanje izmedju radnih niti i UI niti."""

    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "idle"          # idle | recording | thinking | error
        self.finals: list[str] = []
        self.interim = ""
        self.message = ""            # tekst greske ili statusa za HUD
        self.last_text = ""
        self.dirty = True

    def set(self, **kw):
        with self.lock:
            for key, value in kw.items():
                setattr(self, key, value)
            self.dirty = True

    def snapshot(self):
        with self.lock:
            live = stt.join_segments(self.finals)
            if self.interim:
                live = (live + " " + self.interim).strip()
            was_dirty = self.dirty
            self.dirty = False
            return self.phase, live, self.message, was_dirty


class DictateApp(rumps.App):
    def __init__(self):
        super().__init__("Diktat", title=ICON["idle"], quit_button=None)
        self.cfg = config.load()
        self.state = State()
        self.hud = overlay.Overlay()

        self._client = None
        self._project = None
        self._client_error = None
        self._session_lock = threading.Lock()
        self._recorder = None
        self._policy_set = False
        self._error_shown_at = None
        self._record_started_at = 0.0
        self._count_lock = threading.Lock()
        self._pending = 0        # snimci koji se prepoznaju
        self._seq = 0            # redni broj diktata
        self._insert_q: queue.Queue = queue.Queue()

        self._build_menu()
        self._preflight()
        threading.Thread(target=self._insert_worker, daemon=True).start()

        self.listener = hotkey.HotkeyListener(
            self.cfg,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_cancel=self._on_cancel,
        )

    # ------------------------------------------------------------------ UI

    def _build_menu(self):
        self.item_status = rumps.MenuItem("Spremno")
        self.item_status.set_callback(None)

        self.item_copy = rumps.MenuItem(
            "Kopiraj poslednji tekst", callback=self._copy_last
        )

        mode_menu = rumps.MenuItem("Rezim")
        self.item_hold = rumps.MenuItem("Drzi taster", callback=self._set_hold)
        self.item_toggle = rumps.MenuItem("Prekidac", callback=self._set_toggle)
        mode_menu.add(self.item_hold)
        mode_menu.add(self.item_toggle)

        lang_menu = rumps.MenuItem("Jezik")
        self.lang_items = {}
        for code, label in (
            ("sr-RS", "Srpski"),
            ("en-US", "Engleski"),
            ("hr-HR", "Hrvatski"),
        ):
            item = rumps.MenuItem(label, callback=self._make_lang_setter(code))
            self.lang_items[code] = item
            lang_menu.add(item)

        engine_menu = rumps.MenuItem("Motor")
        self.engine_items = {}
        for key, label in (
            ("web", "Besplatni (bez naloga)"),
            ("cloud", "Google Cloud (rec po rec)"),
        ):
            item = rumps.MenuItem(label, callback=self._make_engine_setter(key))
            self.engine_items[key] = item
            engine_menu.add(item)

        self.menu = [
            self.item_status,
            None,
            self.item_copy,
            None,
            engine_menu,
            mode_menu,
            lang_menu,
            None,
            rumps.MenuItem("Otvori config.json", callback=self._open_config),
            None,
            rumps.MenuItem("Izlaz", callback=self._quit),
        ]
        self._sync_menu_marks()

    def _sync_menu_marks(self):
        mode = self.cfg.get("mode", "hold")
        self.item_hold.state = 1 if mode == "hold" else 0
        self.item_toggle.state = 1 if mode == "toggle" else 0
        current = (self.cfg.get("language_codes") or ["sr-RS"])[0]
        for code, item in self.lang_items.items():
            item.state = 1 if code == current else 0
        engine = self.cfg.get("engine", "web")
        for key, item in self.engine_items.items():
            item.state = 1 if key == engine else 0

    def _make_engine_setter(self, engine):
        def setter(_):
            if self.cfg.get("engine") == engine:
                return
            self.cfg["engine"] = engine
            config.save(self.cfg)
            self._client = None
            self._client_error = None
            self.state.set(phase="idle", message="")
            self._preflight()          # cloud trazi kljuc, web ne
            self._sync_menu_marks()

        return setter

    # ------------------------------------------------------- preflight

    def _preflight(self):
        if self.cfg.get("engine", "web") == "cloud":
            try:
                self._project = config.resolve_credentials(self.cfg)
                self._client = stt.make_client(self.cfg)
            except Exception as exc:  # noqa: BLE001
                self._client_error = str(exc)
                self.state.set(phase="error", message=str(exc))
                return
        else:
            # Web motor nema sta da podesava — radi odmah.
            self._client = _WEB

        if not hotkey.accessibility_granted():
            msg = (
                "Nema Accessibility dozvole — hotkey nece raditi. "
                "System Settings > Privacy & Security > Accessibility."
            )
            self._client_error = msg
            self.state.set(phase="error", message=msg)

    # ------------------------------------------------- hotkey callbacks

    def _on_start(self):
        if self._client is None:
            return
        with self._session_lock:
            if self._recorder is not None:
                return
            recorder = audio.Recorder(
                sample_rate=self.cfg["sample_rate"],
                device=self.cfg.get("input_device"),
                max_seconds=self._limit_seconds(),
            )
            try:
                recorder.start()
            except Exception as exc:  # noqa: BLE001
                self.state.set(phase="error", message=f"Mikrofon: {exc}")
                return
            self._recorder = recorder
            self._seq += 1
            seq = self._seq

        self._record_started_at = time.monotonic()
        self.state.set(phase="recording", finals=[], interim="", message="")
        threading.Thread(
            target=self._run_session, args=(recorder, seq), daemon=True
        ).start()

    def _on_stop(self):
        with self._session_lock:
            recorder = self._recorder
        if recorder is None:
            return
        self.state.set(phase="thinking")
        recorder.stop()

    def _on_cancel(self, reason="otkazano"):
        with self._session_lock:
            recorder = self._recorder
            if recorder is None:
                return
            recorder.cancelled = True
        recorder.stop()
        self._settle_phase(reason)

    def _limit_seconds(self) -> float:
        """Gornja granica snimka — web endpoint puca na duzim od ~30s."""
        if self.cfg.get("engine", "web") == "cloud":
            return float(self.cfg.get("max_seconds", 290))
        return float(self.cfg.get("web_max_seconds", 30))

    def _release_recorder(self, recorder):
        """Audio je gotov: pusti mikrofon ODMAH da moze sledeci diktat,
        dok prepoznavanje ovog jos traje u pozadini."""
        if recorder.released:
            return
        recorder.released = True
        with self._session_lock:
            if self._recorder is recorder:
                self._recorder = None
        with self._count_lock:
            self._pending += 1
        recorder.close()

    def _settle_phase(self, message=""):
        """Ne gasi ekran ako je u medjuvremenu poceo nov diktat."""
        with self._session_lock:
            recording = self._recorder is not None
        if recording:
            return
        with self._count_lock:
            busy = self._pending > 0
        self.state.set(
            phase="thinking" if busy else "idle",
            interim="", finals=[], message=message,
        )

    # --------------------------------------------------------- sesija

    def _tracked(self, recorder):
        """Omotac oko chunks() koji pusta mikrofon cim audio stane."""
        try:
            yield from recorder.chunks()
        finally:
            self._release_recorder(recorder)

    def _run_session(self, recorder, seq):
        text = ""
        error = None
        try:
            if self.cfg.get("engine", "web") == "cloud":
                text = stt.stream(
                    self._client,
                    self.cfg,
                    self._project,
                    self._tracked(recorder),
                    on_interim=lambda t: self.state.set(interim=t),
                    on_final=self._append_final,
                )
            else:
                text = self._run_web(recorder)
        except Exception as exc:  # noqa: BLE001
            error = _short_error(exc)
            traceback.print_exc()
        finally:
            self._release_recorder(recorder)

        # Svaka sesija MORA da preda tacno jedan rezultat, inace red stane.
        if recorder.cancelled or error:
            self._insert_q.put((seq, ""))
            if error and not recorder.cancelled:
                self.state.set(phase="error", interim="", message=error)
            else:
                self._settle_phase()
            return

        text = text.strip()
        if not text:
            self._insert_q.put((seq, ""))
            self._settle_phase("(nista)")
            return

        if self.cfg.get("trailing_space", True):
            text += " "
        self.state.set(last_text=text)
        self._insert_q.put((seq, text))

    def _run_web(self, recorder):
        """Web motor: skupi ceo snimak pa ga posalji odjednom."""
        frames = list(self._tracked(recorder))
        if recorder.cancelled:
            return ""
        self._settle_phase()
        text = webstt.recognize(
            b"".join(frames),
            language=(self.cfg.get("language_codes") or ["sr-RS"])[0],
            sample_rate=self.cfg["sample_rate"],
            key=self.cfg.get("web_api_key") or None,
        )
        if text and self.cfg.get("capitalize_first", True):
            text = webstt.tidy(text)
        return text

    def _insert_worker(self):
        """Lepi tekst strogo po redosledu snimanja.

        Prepoznavanja teku paralelno i mogu da se zavrse van reda — kratak
        drugi snimak lako stigne pre dugog prvog. Ovde se ceka na red.
        """
        buffered = {}
        expected = 1
        while True:
            seq, text = self._insert_q.get()
            buffered[seq] = text
            while expected in buffered:
                ready = buffered.pop(expected)
                expected += 1
                with self._count_lock:
                    if self._pending > 0:
                        self._pending -= 1
                if ready:
                    try:
                        insert.insert(
                            ready,
                            method=self.cfg.get("insert_method", "paste"),
                            restore_clipboard=self.cfg.get("restore_clipboard", True),
                        )
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
            self._settle_phase()

    def _append_final(self, segment):
        with self.state.lock:
            self.state.finals.append(segment)
            self.state.interim = ""
            self.state.dirty = True

    # ----------------------------------------------------------- timer

    @rumps.timer(0.05)
    def _tick(self, _sender):
        if not self._policy_set:
            AppKit.NSApplication.sharedApplication().setActivationPolicy_(
                AppKit.NSApplicationActivationPolicyAccessory
            )
            self._policy_set = True

        phase, live, message, dirty = self.state.snapshot()

        # Auto-sklanjanje HUD-a sa greskom mora da radi i kad se stanje ne menja.
        if phase == "error" and self._error_shown_at is not None:
            if time.monotonic() - self._error_shown_at > ERROR_HUD_SECONDS:
                self.hud.hide()
        elif phase != "error":
            self._error_shown_at = None

        # Web motor nema teksta uzivo, pa umesto njega vrtimo merac nivoa —
        # to mora da se osvezava i kad se stanje formalno ne menja.
        if phase == "recording" and not live and self.cfg.get("show_overlay", True):
            recorder = self._recorder
            if recorder is not None:
                if not self.hud.visible:
                    self.hud.show("")
                self.hud.set_text(self._meter_text(recorder))
                self.hud.set_state("thinking" if self._near_limit() else "recording")
                return

        if not dirty:
            return

        self.title = ICON.get(phase, ICON["idle"])

        if phase == "error":
            self.item_status.title = f"Greska: {message[:60]}"
        elif phase == "recording":
            self.item_status.title = "Snimanje…"
        elif phase == "thinking":
            self.item_status.title = "Obrada…"
        else:
            self.item_status.title = "Spremno"

        if not self.cfg.get("show_overlay", True):
            return

        if phase in ("recording", "thinking"):
            shown = live or ("Slusam…" if phase == "recording" else "Obrada…")
            if len(shown) > HUD_MAX_CHARS:
                shown = "…" + shown[-HUD_MAX_CHARS:]
            if not self.hud.visible:
                self.hud.show(shown)
            else:
                self.hud.set_text(shown)
            self.hud.set_state("recording" if phase == "recording" else "thinking")
        elif phase == "error":
            # Greska se pokaze kratko pa se skloni; poruka ostaje u meniju.
            if self._error_shown_at is None:
                self._error_shown_at = time.monotonic()
                self.hud.show(message[:HUD_MAX_CHARS])
                self.hud.set_state("error")
        else:
            self.hud.hide()

    def _meter_text(self, recorder) -> str:
        """Nivo signala + vreme. Broji naviše, a tek pred sam kraj prelazi u
        odbrojavanje — da kratki diktati ne trpe lazan pritisak vremena."""
        elapsed = time.monotonic() - self._record_started_at
        remaining = max(0.0, self._limit_seconds() - elapsed)

        filled = int(min(1.0, recorder.level * 3.0) * len(METER_BLOCKS))
        bar = "".join(
            METER_BLOCKS[min(i, len(METER_BLOCKS) - 1)] if i < filled else "·"
            for i in range(len(METER_BLOCKS))
        )

        if remaining <= WARN_SECONDS:
            clock = f"jos {math.ceil(remaining)}s"
        else:
            clock = f"{int(elapsed // 60)}:{int(elapsed % 60):02d}"

        with self._count_lock:
            pending = self._pending
        badge = f"   ·  obradjujem {pending}" if pending else ""
        return f"{bar}   {clock}   slusam…{badge}"

    def _near_limit(self) -> bool:
        return (
            self._limit_seconds() - (time.monotonic() - self._record_started_at)
        ) <= WARN_SECONDS

    # -------------------------------------------------- menu callbacks

    def _copy_last(self, _):
        if self.state.last_text:
            insert.set_clipboard(self.state.last_text)

    def _set_hold(self, _):
        self._set_mode("hold")

    def _set_toggle(self, _):
        self._set_mode("toggle")

    def _set_mode(self, mode):
        self.cfg["mode"] = mode
        config.save(self.cfg)
        self.listener.mode = mode
        self._sync_menu_marks()

    def _make_lang_setter(self, code):
        def setter(_):
            self.cfg["language_codes"] = [code]
            config.save(self.cfg)
            self._sync_menu_marks()

        return setter

    def _open_config(self, _):
        if not config.CONFIG_PATH.exists():
            config.save(self.cfg)
        AppKit.NSWorkspace.sharedWorkspace().openFile_(str(config.CONFIG_PATH))

    def _quit(self, _):
        try:
            self.listener.stop()
        finally:
            rumps.quit_application()

    # ------------------------------------------------------------- run

    def run(self, **kw):
        self.listener.start()
        super().run(**kw)


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return text[0][:200] if text else exc.__class__.__name__


def main():
    DictateApp().run()
