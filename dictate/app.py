"""Menu-bar aplikacija: drzi desni Command -> diktat -> tekst u aktivnu aplikaciju.

Niti:
  glavna       — rumps / AppKit petlja + Timer koji na 20 Hz osvezava ikonicu i HUD
  pynput       — event tap za hotkey
  sesija       — snimanje + gRPC stream ka Google-u (jedna po diktatu)

AppKit se dira iskljucivo iz glavne niti; radne niti samo upisuju u `State`.
"""

import queue
import re
import threading
import time
import traceback

import AppKit
import rumps
from Foundation import NSAttributedString

from . import (
    audio, config, debugdump, hotkey, insert, listen, overlay, pending, polish, webstt,
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
        self.item_status = rumps.MenuItem("Spremno")
        self.item_status.set_callback(None)

        self.history_menu = rumps.MenuItem("Istorija")
        self.item_pending = rumps.MenuItem(
            "Ponovi neuspele", callback=self._retry_pending
        )
        self.item_debug = rumps.MenuItem(
            "Snimaj za debug", callback=self._toggle_debug
        )
        self.item_refresh = rumps.MenuItem(
            "Osveži audio uređaje", callback=self._refresh_audio
        )
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

        # Jedan izbor umesto tri prekidaca koja su se ponistavala: ranije su
        # "sredi tekst", "sve malim slovima" i "bez interpunkcije" mogli da budu
        # ukljuceni istovremeno, a ishod je zavisio od redosleda u kodu.
        tekst_menu = rumps.MenuItem("Tekst")
        self.style_items = {}
        for kljuc, naziv in (
            ("spoken", "Kako sam izgovorio (mala slova, bez tačaka)"),
            ("written", "Pravopisno sređeno (radi AI)"),
            ("raw", "Sirovo, kako Google vrati"),
        ):
            stavka = rumps.MenuItem(naziv, callback=self._make_style_setter(kljuc))
            self.style_items[kljuc] = stavka
            tekst_menu.add(stavka)
        tekst_menu.add(rumps.separator)
        self.item_ascii = rumps.MenuItem(
            "Bez kvačica (č ć ž š → c c z s)", callback=self._toggle_ascii
        )
        self.item_thousands = rumps.MenuItem(
            "Spoji hiljade (5.000 → 5000)",
            callback=self._make_polish_toggle("join_thousands", True),
        )
        self.item_space = rumps.MenuItem(
            "Razmak na kraju",
            callback=self._make_polish_toggle("trailing_space", True),
        )
        for stavka in (self.item_ascii, self.item_thousands, self.item_space):
            tekst_menu.add(stavka)

        # Sve sto model radi je na jednom mestu, ispod jednog prekidaca.
        ai_menu = rumps.MenuItem("AI")
        self.item_polish = rumps.MenuItem(
            "Uključi AI obradu", callback=self._toggle_polish
        )
        self.item_listen = rumps.MenuItem(
            "Sluša snimak (preciznije prepoznavanje)", callback=self._toggle_listen
        )
        self.item_polish_correct = rumps.MenuItem(
            "Ispravi očigledne greške", callback=self._toggle_polish_level
        )
        self.item_polish_para = rumps.MenuItem(
            "Podeli na pasuse",
            callback=self._make_polish_toggle("polish_paragraphs", True),
        )
        self.item_polish_concise = rumps.MenuItem(
            "Skrati i pojednostavi",
            callback=self._make_polish_toggle("polish_concise", False),
        )
        # Emotikoni su izbor od pet stanja, ne prekidac — gustina se bira istim
        # potezom kojim se ukljucuju.
        self.emoji_menu = rumps.MenuItem("Emotikoni")
        self.emoji_items = {}
        for kljuc, naziv in (
            (None, "Isključeno"),
            ("paragraph", "Na kraju pasusa"),
            ("sentence", "Na kraju rečenice"),
            ("sentence3", "Dva-tri po rečenici"),
            ("dense", "Na svakih par reči"),
        ):
            stavka = rumps.MenuItem(naziv, callback=self._make_emoji_setter(kljuc))
            self.emoji_items[kljuc] = stavka
            self.emoji_menu.add(stavka)
        # Bez callback-a: stavka je samo prikaz. Google ne nudi nacin da se vidi
        # preostala kvota, pa aplikacija broji svoje pozive sama.
        self.item_polish_count = rumps.MenuItem("Poziva modelu danas: 0")
        for stavka in (
            self.item_polish, rumps.separator, self.item_listen,
            self.item_polish_correct, self.item_polish_para,
            self.item_polish_concise, self.emoji_menu,
            rumps.separator, self.item_polish_count,
        ):
            ai_menu.add(stavka)

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

        self.menu = [
            self.item_status,
            None,
            self.history_menu,
            self.item_pending,
            None,
            self.mic_menu,
            self.item_refresh,
            None,
            snimanje_menu,
            tekst_menu,
            ai_menu,
            lang_menu,
            None,
            self.item_debug,
            rumps.MenuItem("Otvori config.json", callback=self._open_config),
            None,
            rumps.MenuItem("Izlaz", callback=self._quit),
        ]

        # Alati se sive dok je glavni prekidac ugasen. Lista parova, ne recnik:
        # rumps MenuItem nije hashable.
        self._polish_callbacks = [
            (self.item_listen, self._toggle_listen),
            (self.item_polish_correct, self._toggle_polish_level),
            (self.item_polish_para, self._make_polish_toggle("polish_paragraphs", True)),
            (self.item_polish_concise, self._make_polish_toggle("polish_concise", False)),
            *[(v, self._make_emoji_setter(k)) for k, v in self.emoji_items.items()],
        ]

        self._rebuild_mic_menu()
        self._rebuild_history_menu()
        self._sync_pending()
        self._sync_menu_marks()

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

        return setter

    def _sync_menu_marks(self):
        mode = self.cfg.get("mode", "hold")
        self.item_hold.state = 1 if mode == "hold" else 0
        self.item_toggle.state = 1 if mode == "toggle" else 0
        self.item_continuous.state = 1 if self.cfg.get("continuous", True) else 0

        stil = config.style(self.cfg)
        for kljuc, stavka in self.style_items.items():
            stavka.state = 1 if kljuc == stil else 0
        self.item_ascii.state = 1 if self.cfg.get("ascii_diacritics", False) else 0
        self.item_thousands.state = 1 if self.cfg.get("join_thousands", True) else 0
        self.item_space.state = 1 if self.cfg.get("trailing_space", True) else 0

        ima_kljuc = polish.available(self.cfg)
        radi = bool(self.cfg.get("polish", False)) and ima_kljuc
        self.item_polish.state = 1 if self.cfg.get("polish", False) else 0
        self.item_polish.title = (
            "Uključi AI obradu" if ima_kljuc else "Nema API ključa (config.json)"
        )
        self.item_listen.state = 1 if listen.enabled(self.cfg) else 0
        self.item_polish_correct.state = (
            1 if self.cfg.get("polish_level", "correct") == "correct" else 0
        )
        self.item_polish_para.state = 1 if self.cfg.get("polish_paragraphs", True) else 0
        self.item_polish_concise.state = 1 if self.cfg.get("polish_concise", False) else 0

        gustina = polish.emoji_rate(self.cfg) if self.cfg.get("polish_emoji", False) else None
        for kljuc, stavka in self.emoji_items.items():
            stavka.state = 1 if kljuc == gustina else 0
        self.emoji_menu.title = "Emotikoni: " + (
            self.emoji_items[gustina].title.lower() if gustina else "isključeno"
        )

        # Alat se ne bira dok je glavni prekidac ugasen. Sivi se skidanjem
        # callback-a, ne sa setEnabled_: NSMenu sam ukljucuje stavke koje imaju
        # akciju, pa bi setEnabled_ bio pregazen pri sledecem otvaranju menija.
        for stavka, cb in self._polish_callbacks:
            aktivan = radi
            if stavka is self.item_polish_correct:
                # Ispravljanje ima smisla samo kad model uopste sredjuje tekst.
                aktivan = radi and stil == "written"
            stavka.set_callback(cb if aktivan else None)
        self.item_polish_count.title = f"Poziva modelu danas: {self._polish_today()}"

        # Stil „pravopisno sredjeno" bez ukljucenog AI-ja nema ko da izvrsi.
        self.style_items["written"].title = (
            "Pravopisno sređeno (radi AI)" if radi
            else "Pravopisno sređeno — traži uključen AI"
        )

        current = self.cfg.get("language", "sr-RS")
        for code, item in self.lang_items.items():
            item.state = 1 if code == current else 0

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

        self._deliver(ticket, self._finish(text), recorder.session)

    def _finish(self, text: str) -> str:
        if self.cfg.get("trailing_space", True):
            text += " "
        return text

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
            profanity_filter=bool(self.cfg.get("profanity_filter", False)),
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
        if not pcm or not listen.enabled(self.cfg):
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
        try:
            ispravljen = listen.check_batch(delovi, tekst, self.cfg)
            self._count_polish()
            if ispravljen != tekst:
                print(f"[diktat] AI slušao {len(delovi)} segm.: {tekst!r} -> {ispravljen!r}")
            return ispravljen, True
        except Exception as exc:  # noqa: BLE001
            print(f"[diktat] provera snimka nije uspela: {exc}")
            return tekst, False

    def _apply_rules(self, text: str) -> str:
        """Nasa pravila nad jednim komadom teksta, bez prelamanja redova."""
        if self.cfg.get("join_thousands", True):
            text = webstt.join_thousands(text)
        # „Kako sam izgovorio" znaci mala slova i bez interpunkcije; „sirovo"
        # ostavlja ono sto Google vrati. „Pravopisno sredjeno" ovde nema sta da
        # radi — to je posao modela, pa tekst prolazi nedirnut.
        izgovoreno = config.style(self.cfg) == "spoken"
        if izgovoreno:
            text = webstt.strip_punctuation(text)
            text = text.lower()
        if self.cfg.get("ascii_diacritics", False):
            text = webstt.to_ascii(text)
        if not izgovoreno and self.cfg.get("capitalize_first", False):
            return webstt.tidy(text)
        return text

    def _after_model(self, text: str) -> str:
        """Zavrsna podesavanja nad tekstom koji je model vec sredio.

        Mala slova i brisanje interpunkcije se ovde NE primenjuju: to je bas
        posao koji je model dobio, pa bi jedno gasilo drugo. Ostaje ono sto se
        sa njegovim oblikovanjem ne sudara.
        """
        if self.cfg.get("join_thousands", True):
            text = webstt.join_thousands(text)
        if self.cfg.get("ascii_diacritics", False):
            text = webstt.to_ascii(text)
        return text

    def _rules_over_paragraphs(self, text: str) -> str:
        """Ista pravila, ali podela na pasuse prezivljava.

        `strip_punctuation` skuplja sve razmake u jedan, pa bi nad celim tekstom
        pojeo prazne redove koje je model namerno stavio.
        """
        return "\n\n".join(
            self._apply_rules(deo.strip())
            for deo in re.split(r"\n\s*\n", text)
            if deo.strip()
        )

    def _transcribe(self, recorder):
        """Na dugom diktatu sece snimak na pauzama i salje delove na obradu
        dok ti jos pricas — tako nema cekanja na kraju."""
        if not self._segmenting():
            session = self._dump.session() if self._dump else None
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
                            method=self.cfg.get("insert_method", "paste"),
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

    def _count_polish(self):
        """Brojac poziva po danu — Google ne nudi nacin da se vidi preostala kvota."""
        import datetime

        danas = datetime.date.today().isoformat()
        if self.cfg.get("polish_count_day") != danas:
            self.cfg["polish_count_day"] = danas
            self.cfg["polish_count"] = 0
        self.cfg["polish_count"] = int(self.cfg.get("polish_count", 0)) + 1
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
            self._doteraj(tekst, sredjeno) if self._formal()
            else self._rules_over_paragraphs(tekst)
        )
        with self._count_lock:
            self._polishing_count = max(0, self._polishing_count - 1)
            self._polishing = self._polishing_count > 0
        if self.cfg.get("trailing_space", True):
            doteran += " "
        self._remember(doteran)
        try:
            insert.insert(
                doteran,
                method=self.cfg.get("insert_method", "paste"),
                restore_clipboard=self.cfg.get("restore_clipboard", True),
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        self._settle_phase()

    def _doteraj(self, tekst: str, vec_sredjeno=False) -> str:
        try:
            doteran = polish.polish(tekst, self.cfg, vec_sredjeno=vec_sredjeno)
            self._count_polish()
            if self.cfg.get("polish_emoji", False):
                doteran = polish.bez_ponavljanja(doteran)
                # Istorija znakova ide u sledeci zahtev: model nema pamcenje
                # izmedju poziva, pa bi inace svaki put posegnuo za istima.
                polish.zapamti_emoji(doteran, self.cfg)
                config.save(self.cfg)
            if polish.tidy_on(self.cfg) or vec_sredjeno:
                # Uz sredjivanje ostaju samo podesavanja koja se sa njim ne
                # sudaraju — tekst je modelu isao nedirnut, pa bi inace izostala.
                doteran = self._after_model(doteran)
            else:
                # Kad sredjivanje nije trazeno, model ga svejedno uradi cim
                # prepisuje recenice — skracivanje ih vraca pravopisno uredne.
                # Uputstvo to ne resava pouzdano, pa presudjuju nasa pravila.
                doteran = self._rules_over_paragraphs(doteran)
            return doteran
        except Exception as exc:  # noqa: BLE001
            # Nedoteran tekst je bolji nego nikakav — model je dodatak, ne uslov.
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
            self._sync_pending()

        phase, message, dirty = self.state.snapshot()

        # Auto-sklanjanje HUD-a sa greskom mora da radi i kad se stanje ne menja.
        if phase == "error" and self._error_shown_at is not None:
            if time.monotonic() - self._error_shown_at > ERROR_HUD_SECONDS:
                self.hud.hide()
        elif phase != "error":
            self._error_shown_at = None

        # Dok snima, u menu baru stoji proteklo vreme umesto ikonice. Ova grana
        # mora da tece i kad se stanje formalno ne menja, jer sat ide sam.
        if phase == "recording" and self._recorder is not None:
            clock = self._clock_text()
            self._last_clock = clock   # ostaje i dok se posle obradjuje
            self._set_menubar(clock, self._title_color())
            self.item_status.title = "Snimanje…"
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

        if phase == "polishing":
            # Plavo + "AI": korisnik mora da zna da je otislo modelu i da se ceka.
            self._set_menubar("AI", "polishing")
            self.item_status.title = "Doterujem tekst…"
        elif phase == "thinking":
            # Cifre ostaju, samo pozute — obrada traje par sekundi i tako se
            # vidi da jos nesto radi, umesto da naslov skoci na ikonicu.
            self._set_menubar(self._last_clock or ICON["idle"], "busy")
        else:
            self._set_menubar(ICON.get(phase, ICON["idle"]))

        if phase == "error":
            self.item_status.title = f"Greška: {message[:60]}"
        elif phase == "recording":
            self.item_status.title = "Snimanje…"
        elif phase == "thinking":
            self.item_status.title = "Obrada…"
        else:
            self.item_status.title = "Spremno"

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
        if self._polishing:
            return "polishing"
        """Zuta ima prednost: ako se prethodni tekst jos obradjuje, to je
        vaznije od toga koliko dugo traje novo snimanje."""
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

    def _retry_pending(self, _):
        """Posalji ponovo sve sto ranije nije proslo, po redu snimanja."""
        files = self._pending_store.list()
        if not files:
            return
        self.item_status.title = f"Ponavljam {len(files)}…"
        threading.Thread(target=self._do_retry, args=(files,), daemon=True).start()

    def _do_retry(self, files):
        sesija = self._nova_sesija()
        for path in files:
            try:
                text = self._recognize(self._pending_store.load(path))
            except Exception as exc:  # noqa: BLE001
                self.state.set(phase="error", message=_short_error(exc))
                return
            self._pending_store.remove(path)
            if text:
                self._deliver(self._next_ticket(sesija), self._finish(text), sesija)
        self._history_dirty = True
        self._settle_phase()

    def _sync_pending(self):
        count = len(self._pending_store.list())
        self.item_pending.title = (
            f"Ponovi neuspele ({count})" if count else "Ponovi neuspele"
        )
        self.item_pending.set_callback(self._retry_pending if count else None)

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
            self.item_status.title = "Upiši polish_api_key u config.json"
            return
        self.cfg["audio_check"] = not bool(self.cfg.get("audio_check", False))
        config.save(self.cfg)
        self._sync_menu_marks()

    def _toggle_polish(self, _):
        if not polish.available(self.cfg):
            self.item_status.title = "Upiši polish_api_key u config.json"
            return
        self.cfg["polish"] = not bool(self.cfg.get("polish", False))
        config.save(self.cfg)
        if self.cfg["polish"] and not polish.tools(self.cfg):
            self.item_status.title = "Izaberi bar jedan alat ispod"
        self._sync_menu_marks()

    def _toggle_polish_level(self, _):
        nivo = "format" if self.cfg.get("polish_level", "correct") == "correct" else "correct"
        self.cfg["polish_level"] = nivo
        config.save(self.cfg)
        self._sync_menu_marks()

    def _batch(self) -> bool:
        """Ceka li se kraj diktata zbog provere snimka."""
        return listen.enabled(self.cfg)

    def _deferred(self) -> bool:
        """Ceka li se kraj diktata uopste — zbog modela ili zbog provere."""
        return self._formal() or self._batch()

    def _formal(self) -> bool:
        """Ceka li se ceo diktat zbog modela.

        Ukljucena obrada bez ijednog izabranog alata nema sta da posalje, pa se
        tekst lepi odmah kao i inace — bez toga bi diktat visio na praznom pozivu.
        """
        return (
            bool(self.cfg.get("polish", False))
            and polish.available(self.cfg)
            and bool(polish.tools(self.cfg))
        )

    def _make_emoji_setter(self, rate):
        """None gasi emotikone; ostalo ih pali i postavlja gustinu."""
        def setter(_):
            self.cfg["polish_emoji"] = rate is not None
            if rate is not None:
                self.cfg["polish_emoji_rate"] = rate
            config.save(self.cfg)
            self._sync_menu_marks()
        return setter

    def _make_style_setter(self, stil):
        def setter(_):
            self.cfg["text_style"] = stil
            config.save(self.cfg)
            if stil == "written" and not (
                self.cfg.get("polish") and polish.available(self.cfg)
            ):
                self.item_status.title = "Uključi AI da bi sređivao tekst"
            self._sync_menu_marks()
        return setter

    def _make_polish_toggle(self, key, default):
        def toggle(_):
            self.cfg[key] = not bool(self.cfg.get(key, default))
            config.save(self.cfg)
            self._sync_menu_marks()
        return toggle

    def _toggle_continuous(self, _):
        self.cfg["continuous"] = not bool(self.cfg.get("continuous", True))
        config.save(self.cfg)
        self._sync_menu_marks()

    def _set_mode(self, mode):
        self.cfg["mode"] = mode
        config.save(self.cfg)
        self.listener.mode = mode
        self._sync_menu_marks()

    def _toggle_ascii(self, _):
        self.cfg["ascii_diacritics"] = not bool(
            self.cfg.get("ascii_diacritics", False)
        )
        config.save(self.cfg)
        self._sync_menu_marks()

    def _make_lang_setter(self, code):
        def setter(_):
            self.cfg["language"] = code
            config.save(self.cfg)
            self._sync_menu_marks()

        return setter

    def _refresh_audio(self, _):
        audio.refresh_devices()
        self._rebuild_mic_menu()
        self.state.set(phase="idle", message="")
        self.item_status.title = f"Mikrofon: {audio.current_input_name()[:40]}"

    def _apply_debug(self, on):
        self._dump = (
            debugdump.DebugDump(
                self.cfg.get("debug_dir", "~/Diktat-debug"), self.cfg["sample_rate"]
            )
            if on
            else None
        )
        self.item_debug.state = 1 if on else 0

    def _toggle_debug(self, _):
        on = not bool(self.cfg.get("debug", False))
        self.cfg["debug"] = on
        config.save(self.cfg)
        self._apply_debug(on)
        if on:
            AppKit.NSWorkspace.sharedWorkspace().openFile_(str(self._dump.dir))

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


def _label(text: str, limit=52) -> str:
    jedan_red = " ".join(text.split())
    return jedan_red if len(jedan_red) <= limit else jedan_red[: limit - 1] + "…"


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return text[0][:200] if text else exc.__class__.__name__


def main():
    DictateApp().run()
