"""macOS prozor sa podesavanjima, podeljen na kartice.

Ranije je sve stajalo u jednoj koloni od preko dve hiljade piksela, pa se do
API kljuceva skrolovalo pola ekrana. Sada je isti sadrzaj podeljen na kartice
po pitanju na koje odgovara (Snimanje i tekst, Istorija, Kljucevi), a visina
svake se racuna iz sadrzaja. Zaglavlje nosi ono sto ne pripada nijednoj
kartici: snimljeno vreme, zaustavljanje snimanja i izlaz iz aplikacije.

Sadrzaj stoji u koloni fiksne sirine koja ostaje na SREDINI: preko celog ekrana
bi redovi inace bili dugacki po metar, a polja za kljuceve rastegnuta preko
cele sirine.

Dokument je „flipped" (nula je gore): AppKit inace racuna od dna, pa je kraci
sadrzaj padao na dno prozora i ostavljao praznu polovinu iznad sebe.

Podesavanje koje trenutni izbor ne koristi se SKLANJA, ne sivi — sivo
podesavanje je gore od nepostojeceg, jer izgleda kao greska. Zato raspored nije
fiksan: kartica pamti svoje redove i pri svakoj izmeni ih ponovo slaze, pa
sklonjen red ne ostavlja rupu.
"""

import objc
import AppKit
from Foundation import NSMakeRect, NSMakeSize

from . import audio, config, hotkey


# Naziv izvora transkripcije stoji na JEDNOM mestu: iz njega se pravi spisak u
# prozoru, iz njega se cita nazad izabrana stavka. Dva spiska bi se razisla cim
# se doda treci izvor — bas to se i desilo kad su dosli Gemini modeli.
PROVIDER_TITLES = {
    "google": "Google Speech-to-Text",
    "openai": "OpenAI GPT Transcribe",
    "gemini_live": "Gemini 3.5 Transcribe Live",
}

MIKROFON_PODRAZUMEVANI = "Sistemski podrazumevani"

COLUMN = 520.0        # sirina kolone sa sadrzajem; ostatak je margina
TOP = 22.0            # razmak od vrha kartice do prvog reda
GAP = 8.0             # razmak izmedju dve kontrole
SECTION_GAP = 26.0    # razmak PRE naslova grupe
TITLE_GAP = 12.0      # razmak izmedju naslova grupe i prve kontrole


def provider_from_title(title: str) -> str:
    """Izabrana stavka -> kljuc podesavanja; nepoznato pada na Google."""
    for ime, naslov in PROVIDER_TITLES.items():
        if naslov == title:
            return ime
    return "google"


def trajanje(seconds: float) -> str:
    """Sekunde u „2 h 15 min 30 s"; nule se ne ispisuju."""
    ukupno = max(0, int(seconds))
    sati, ostatak = divmod(ukupno, 3600)
    minuti, sekunde = divmod(ostatak, 60)
    delovi = []
    if sati:
        delovi.append(f"{sati} h")
    if minuti:
        delovi.append(f"{minuti} min")
    if sekunde or not delovi:
        delovi.append(f"{sekunde} s")
    return " ".join(delovi)


class _FlippedView(AppKit.NSView):
    """Pogled kome je nula GORE.

    Bez ovoga AppKit racuna od dna: kartica kraca od prozora zalepi se za dno,
    pa iznad sadrzaja stoji prazna polovina ekrana.
    """

    def isFlipped(self):  # noqa: N802 - ime trazi AppKit
        return True


class _WindowDelegate(AppKit.NSObject):
    """Dok je prozor otvoren, Diktat je obicna aplikacija.

    Menu-bar aplikacija je `Accessory`: nema ikonicu u Dock-u ni svoj meni, pa
    se svaki njen prozor ponasa kao pomocni panel iznad tudje aplikacije. Za
    vreme dok podesavanja stoje otvorena prelazi se na `Regular`, pa prozor ima
    svoje mesto u Dock-u, u Cmd+Tab-u i u Mission Control-u; po zatvaranju se
    vraca, da ikonica ne ostane da visi.
    """

    def initWithOwner_(self, owner):
        self = objc.super(_WindowDelegate, self).init()
        if self is not None:
            self._owner = owner
        return self

    def windowWillClose_(self, _notification):  # noqa: N802 - ime trazi AppKit
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory
        )


class _Row:
    """Jedan red kartice; `vidljivo` odlucuje da li se uopste crta."""

    __slots__ = ("view", "height", "gap", "inset", "width", "vidljivo")

    def __init__(self, view, height, gap, inset, width, vidljivo):
        self.view = view
        self.height = height
        self.gap = gap
        self.inset = inset
        self.width = width
        self.vidljivo = vidljivo

    def prikazi(self) -> bool:
        return True if self.vidljivo is None else bool(self.vidljivo())


class _Page:
    """Jedna kartica: redovi se slazu odozgo nadole, visina se racuna sama."""

    def __init__(self, label: str, width: float):
        self.width = width
        self.scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, width, 400)
        )
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setBorderType_(AppKit.NSNoBorder)
        self.scroll.setDrawsBackground_(False)
        self.scroll.setAutoresizingMask_(
            AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable
        )
        self.document = _FlippedView.alloc().initWithFrame_(
            NSMakeRect(0, 0, width, 400)
        )
        self.document.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        # Kolona ima fiksnu sirinu i obe margine gipke, pa ostaje na sredini i
        # kad se prozor rasiri preko celog ekrana.
        self.column = _FlippedView.alloc().initWithFrame_(
            NSMakeRect((width - COLUMN) / 2, TOP, COLUMN, 10)
        )
        self.column.setAutoresizingMask_(
            AppKit.NSViewMinXMargin | AppKit.NSViewMaxXMargin
        )
        self.document.addSubview_(self.column)
        self.scroll.setDocumentView_(self.document)

        self.item = AppKit.NSTabViewItem.alloc().initWithIdentifier_(label)
        self.item.setLabel_(label)
        self.item.setView_(self.scroll)

        self.rows: list[_Row] = []

    def place(self, view, height, gap=GAP, inset=0.0, vidljivo=None):
        self.column.addSubview_(view)
        self.rows.append(_Row(view, height, gap, inset, COLUMN - inset, vidljivo))
        return view

    def place_left(self, view, height, width, gap=GAP, inset=0.0, vidljivo=None):
        """Kontrola prirodne sirine (dugme), poravnata levo."""
        self.column.addSubview_(view)
        self.rows.append(_Row(view, height, gap, inset, width, vidljivo))
        return view

    def space(self, amount=SECTION_GAP, vidljivo=None):
        """Prazan razmak; nestaje zajedno sa grupom kojoj pripada."""
        self.rows.append(_Row(None, amount, 0.0, 0.0, 0.0, vidljivo))

    def relayout(self):
        y = 0.0
        for row in self.rows:
            prikazan = row.prikazi()
            if row.view is None:
                if prikazan and y > 0:
                    y += row.height
                continue
            row.view.setHidden_(not prikazan)
            if not prikazan:
                continue
            row.view.setFrame_(NSMakeRect(row.inset, y, row.width, row.height))
            y += row.height + row.gap

        visina = y + TOP
        self.column.setFrameSize_(NSMakeSize(COLUMN, y))
        self.document.setFrame_(NSMakeRect(0, 0, self.width, visina))
        self.column.setFrameOrigin_(
            AppKit.NSMakePoint(max(0.0, (self.width - COLUMN) / 2), TOP)
        )


class SettingsWindow:
    WIDTH = 640.0
    HEIGHT = 620.0
    PAGE_WIDTH = WIDTH - 64.0

    def __init__(self, app):
        self.app = app
        self.window = None
        self.tabs = None
        self.pages = []
        self.delegate = None
        self.controls = {}
        self.history_buttons = []
        self.microphone_popup = None
        self.stop_button = None
        self.quit_button = None
        self.recorded_label = None
        self._history_len = 0
        self._accessibility_ok = True
        self._mikrofon_ok = True

    # ------------------------------------------------------------ gradnja

    def show(self):
        if self.window is None:
            self._build()
        else:
            self.refresh()
        self._activate()

    def hide(self):
        """Drugi klik na ikonicu sklanja prozor."""
        if self.window is not None:
            self.window.performClose_(None)

    def visible(self) -> bool:
        return self.window is not None and bool(self.window.isVisible())

    def _activate(self):
        nsapp = AppKit.NSApplication.sharedApplication()
        nsapp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        self.window.makeKeyAndOrderFront_(None)
        nsapp.activateIgnoringOtherApps_(True)

    def _build(self):
        masks = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
            | AppKit.NSWindowStyleMaskResizable
        )
        self.window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, self.WIDTH, self.HEIGHT),
            masks,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Diktat — Podešavanja")
        self.window.setReleasedWhenClosed_(False)
        self.window.setMinSize_(NSMakeSize(520, 460))
        # Pun ekran i svoje mesto u Mission Control-u: bez ovoga se prozor
        # menu-bar aplikacije ponasa kao pomocni panel iznad tudjeg prozora.
        self.window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorFullScreenPrimary
            | AppKit.NSWindowCollectionBehaviorManaged
        )
        self.delegate = _WindowDelegate.alloc().initWithOwner_(self)
        self.window.setDelegate_(self.delegate)

        content = AppKit.NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        )

        # Zaglavlje nosi ono sto ne pripada nijednoj kartici. „Zaustavi
        # snimanje" mora da se vidi sa svake kartice, a izlaz iz aplikacije
        # nema svoju grupu podesavanja.
        self.recorded_label = self._plain_label("", 12, alpha=0.6)
        self.recorded_label.setFrame_(NSMakeRect(20, self.HEIGHT - 36, 280, 18))
        self.recorded_label.setAutoresizingMask_(AppKit.NSViewMinYMargin)
        content.addSubview_(self.recorded_label)

        self.quit_button = self._plain_button("Zatvori Diktat", "quit")
        self.quit_button.setFrame_(NSMakeRect(self.WIDTH - 156, self.HEIGHT - 42, 140, 28))
        self.quit_button.setAutoresizingMask_(
            AppKit.NSViewMinXMargin | AppKit.NSViewMinYMargin
        )
        content.addSubview_(self.quit_button)

        self.stop_button = self._plain_button("Zaustavi snimanje", "stop_recording")
        self.stop_button.setFrame_(NSMakeRect(self.WIDTH - 330, self.HEIGHT - 42, 166, 28))
        self.stop_button.setAutoresizingMask_(
            AppKit.NSViewMinXMargin | AppKit.NSViewMinYMargin
        )
        content.addSubview_(self.stop_button)

        self.tabs = AppKit.NSTabView.alloc().initWithFrame_(
            NSMakeRect(12, 12, self.WIDTH - 24, self.HEIGHT - 56)
        )
        self.tabs.setAutoresizingMask_(
            AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable
        )
        content.addSubview_(self.tabs)
        self.window.setContentView_(content)

        self.pages = [
            self._page_diktat(),
            self._page_istorija(),
            self._page_kljucevi(),
        ]
        for page in self.pages:
            self.tabs.addTabViewItem_(page.item)

        self.refresh()
        self.refresh_recording()
        self.window.center()

    # ------------------------------------------------------------- uslovi

    def _provider(self) -> str:
        return self.app.cfg.get("transcription_provider", "google")

    def _samo_za(self, *imena):
        """Uslov: red se vidi samo uz navedene izvore transkripcije."""
        return lambda: self._provider() in imena

    def _ai_ukljucen(self) -> bool:
        return config.ai_obrada(self.app.cfg)

    def _lokalna_ukljucena(self) -> bool:
        """Sva cetiri ugasena znaci „pravilno", tj. grupa je iskljucena."""
        return not config.pravilno(self.app.cfg)

    def _dozvole_ok(self) -> bool:
        return self._accessibility_ok and self._mikrofon_ok

    # ----------------------------------------------------------- kartice

    def _page_diktat(self) -> _Page:
        """Snimanje i tekst u jednoj kartici: to je jedan tok, od glasa do polja."""
        page = _Page("Snimanje i tekst", self.PAGE_WIDTH)

        self._section(page, "Mikrofon i aktivacija")
        self._popup(
            page, "Mikrofon", "input_device",
            [MIKROFON_PODRAZUMEVANI, *audio.input_devices()],
            self.app.cfg.get("input_device") or MIKROFON_PODRAZUMEVANI,
        )
        self.microphone_popup = self.controls["input_device"]
        self._popup(
            page, "Aktivacija", "mode", ["Prekidač", "Drži taster"],
            "Prekidač" if self.app.cfg.get("mode") == "toggle" else "Drži taster",
        )
        self._checkbox(page, "Aktiviraj i tasterom § (znak se ne upisuje)",
                       "hotkey_section", True)
        self._checkbox(page, "Aktiviraj i tasterom ` (znak se ne upisuje)",
                       "hotkey_grave", False)
        self._checkbox(
            page, "Neprekidno snimanje (seče na pauzama)", "continuous", True,
            vidljivo=self._samo_za("google", "gemini_live"),
        )

        self._section(page, "Prepoznavanje govora")
        self._popup(
            page, "Servis", "transcription_provider",
            list(PROVIDER_TITLES.values()),
            PROVIDER_TITLES.get(self._provider(), PROVIDER_TITLES["google"]),
        )
        self._checkbox(
            page, "Prikaži prepis uživo u okviru na ekranu", "live_preview", True,
            vidljivo=self._samo_za("gemini_live"),
        )
        self._checkbox(
            page, "Upisuj tekst tokom snimanja u aktivno polje", "gemini_live_insert",
            False, vidljivo=self._samo_za("gemini_live"),
        )
        self._checkbox(
            page, "OpenAI dugi diktat (do 60 min)", "openai_long_recording", True,
            vidljivo=self._samo_za("openai"),
        )

        # Provera prepisa ima smisla samo uz besplatni Google: uz OpenAI i
        # Gemini bi isti zvuk isao drugi put, slabijem modelu.
        samo_google = self._samo_za("google")
        self._section(page, "Provera prepisa", "Drugi model sluša isti snimak.",
                      vidljivo=samo_google)
        self._checkbox(page, "Gemini sluša snimak", "audio_check", False,
                       vidljivo=samo_google)
        self._checkbox(page, "Groq (Whisper + GPT-OSS)", "groq_enabled", False,
                       vidljivo=samo_google)

        self._section(page, "AI obrada teksta")
        self._checkbox(page, "Uključi AI obradu", "ai_obrada", True)
        ukljucen = self._ai_ukljucen
        self._popup(
            page, "Model", "text_model",
            ["Gemini", "Groq GPT-OSS 120B"],
            "Groq GPT-OSS 120B" if self.app.cfg.get("text_model") == "groq" else "Gemini",
            vidljivo=ukljucen,
        )
        self._checkbox(page, "Sredi tekst (tačke i velika slova)", "text_style_written",
                       False, vidljivo=ukljucen)
        self._checkbox(page, "Podeli na pasuse", "polish_paragraphs", True,
                       vidljivo=ukljucen)
        self._checkbox(page, "Sažmi u tačke", "polish_bullets", False, vidljivo=ukljucen)
        self._checkbox(page, "Izbaci ponavljanja", "polish_dedupe", False,
                       vidljivo=ukljucen)

        # Ista logika kao iznad: prekidac grupe, pa se pravila sklone kad su
        # ugasena. „Ukljuceno" je izvedeno iz samih pravila, ne pamti se
        # zasebno — inace bi rucno gasenje jednog ostavilo prekidac da laze.
        self._section(page, "Lokalna pravila", "Rade i bez AI modela, odmah po prepisu.")
        self._checkbox(page, "Uključi lokalna pravila", "lokalna_pravila", True)
        pravila = self._lokalna_ukljucena
        self._checkbox(page, "Sva slova mala", "lowercase", True, vidljivo=pravila)
        self._checkbox(page, "Bez interpunkcije", "strip_punctuation", True,
                       vidljivo=pravila)
        self._checkbox(page, "Bez kvačica (č ć ž š → c c z s)", "ascii_diacritics",
                       False, vidljivo=pravila)
        self._checkbox(page, "Skraćenice (ne znam → nzm)", "abbreviations", True,
                       vidljivo=pravila)
        self._hint(page, "Isključeno: tekst izlazi pravopisno uređen.",
                   vidljivo=lambda: not self._lokalna_ukljucena())

        # Dozvola koja postoji nema šta da se traži; grupa se vidi samo kad
        # nešto zaista fali.
        self._section(page, "Dozvole", vidljivo=lambda: not self._dozvole_ok())
        self._hint(page, "Bez Accessibility dozvole tekst završava u clipboard-u "
                         "umesto u aktivnom polju.",
                   vidljivo=lambda: not self._accessibility_ok)
        self._button(page, "Otvori Accessibility", "accessibility",
                     vidljivo=lambda: not self._accessibility_ok)
        self._hint(page, "Snimanje je zabranjeno u sistemskim podešavanjima.",
                   vidljivo=lambda: not self._mikrofon_ok)
        self._button(page, "Otvori podešavanja mikrofona", "microphone",
                     vidljivo=lambda: not self._mikrofon_ok)
        return page

    def _page_istorija(self) -> _Page:
        page = _Page("Istorija", self.PAGE_WIDTH)
        self._section(page, "Poslednjih pet diktata", "Klikni na red da kopiraš tekst.")
        for index in range(5):
            self.history_buttons.append(
                self._button(
                    page, "", f"copy_history_{index}", full_width=True,
                    vidljivo=lambda i=index: i < self._history_len,
                )
            )
        self._hint(page, "Još ništa nije izdiktirano.",
                   vidljivo=lambda: self._history_len == 0)
        return page

    def _page_kljucevi(self) -> _Page:
        page = _Page("Ključevi", self.PAGE_WIDTH)
        self._section(page, "API ključevi", "Ostaju lokalno u config.json.")
        self._field(page, "Gemini (transkripcija Live i obrada teksta)", "polish_api_key",
                    secure=True)
        self._field(page, "Groq (obrada teksta i provera prepisa)", "groq_api_key",
                    secure=True)
        self._field(page, "OpenAI (GPT transkripcija)", "openai_api_key", secure=True)
        page.space(12.0)
        self._button(page, "Proveri sve ključeve", "check_api")
        return page

    # --------------------------------------------------------- kontrole

    def _plain_label(self, text, size=13, bold=False, alpha=1.0):
        field = AppKit.NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        field.setStringValue_(text)
        field.setEditable_(False)
        field.setSelectable_(False)
        field.setBordered_(False)
        field.setDrawsBackground_(False)
        field.setFont_(
            AppKit.NSFont.boldSystemFontOfSize_(size) if bold
            else AppKit.NSFont.systemFontOfSize_(size)
        )
        field.setTextColor_(AppKit.NSColor.labelColor())
        field.setAlphaValue_(alpha)
        return field

    def _text_height(self, field, width, fallback) -> float:
        """Visina prelomljenog teksta; opis u dva reda ne sme da se seče."""
        try:
            field.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
            cell = field.cell()
            cell.setWraps_(True)
            visina = cell.cellSizeForBounds_(NSMakeRect(0, 0, width, 10_000)).height
            return max(fallback, float(visina) + 2)
        except Exception:          # noqa: BLE001 — crtanje ne sme da obori prozor
            return fallback

    def _section(self, page, title, description="", vidljivo=None):
        page.space(vidljivo=vidljivo)
        page.place(self._plain_label(title, 15, bold=True), 22,
                   gap=(4.0 if description else TITLE_GAP), vidljivo=vidljivo)
        if description:
            self._hint(page, description, gap=TITLE_GAP, vidljivo=vidljivo)

    def _hint(self, page, text, gap=GAP, inset=0.0, vidljivo=None):
        field = self._plain_label(text, 12, alpha=0.6)
        visina = self._text_height(field, COLUMN - inset, 17.0)
        return page.place(field, visina, gap=gap, inset=inset, vidljivo=vidljivo)

    def _plain_button(self, title, identifier):
        item = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 30))
        item.setTitle_(title)
        item.setBezelStyle_(AppKit.NSBezelStyleRounded)
        item.setTarget_(self.app)
        item.setAction_("settingsButton:")
        item.setIdentifier_(identifier)
        return item

    def _button(self, page, title, identifier, full_width=False, vidljivo=None):
        item = self._plain_button(title, identifier)
        if full_width:
            # Redovi istorije nose ceo tekst, pa idu preko cele kolone i
            # poravnati su levo — centriran dugacak prepis se cita gore.
            try:
                item.cell().setAlignment_(AppKit.NSTextAlignmentLeft)
            except Exception:      # noqa: BLE001
                pass
            return page.place(item, 26, gap=6.0, vidljivo=vidljivo)
        item.sizeToFit()
        sirina = min(COLUMN, max(item.frame().size.width + 28, 150.0))
        return page.place_left(item, 30, sirina, gap=6.0, vidljivo=vidljivo)

    def _checkbox(self, page, title, key, default=None, inset=0.0, vidljivo=None):
        item = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        item.setButtonType_(AppKit.NSSwitchButton)
        item.setTitle_(title)
        item.setTarget_(self.app)
        item.setAction_("settingsCheckbox:")
        item.setIdentifier_(key)
        item.setState_(
            AppKit.NSControlStateValueOn if bool(self.app.cfg.get(key, default))
            else AppKit.NSControlStateValueOff
        )
        control = page.place(item, 20, gap=6.0, inset=inset, vidljivo=vidljivo)
        self.controls[key] = control
        return control

    def _popup(self, page, title, key, values, selected, vidljivo=None):
        page.place(self._plain_label(title, 12, alpha=0.6), 16, gap=2.0,
                   vidljivo=vidljivo)
        item = AppKit.NSPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 26))
        item.addItemsWithTitles_(values)
        if selected in values:
            item.selectItemWithTitle_(selected)
        item.setTarget_(self.app)
        item.setAction_("settingsPopup:")
        item.setIdentifier_(key)
        control = page.place(item, 26, vidljivo=vidljivo)
        self.controls[key] = control
        return control

    def _field(self, page, title, key, secure=False, vidljivo=None):
        page.place(self._plain_label(title, 12, alpha=0.6), 16, gap=2.0,
                   vidljivo=vidljivo)
        cls = AppKit.NSSecureTextField if secure else AppKit.NSTextField
        item = cls.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 24))
        item.setStringValue_(str(self.app.cfg.get(key, "")))
        item.setIdentifier_(key)
        item.setDelegate_(self.app)
        control = page.place(item, 24, gap=10.0, vidljivo=vidljivo)
        self.controls[key] = control
        return control

    # --------------------------------------------------------- osvezavanje

    def refresh(self):
        if self.window is None:
            return
        audio.refresh_devices()
        if self.microphone_popup is not None:
            selected = self.app.cfg.get("input_device") or MIKROFON_PODRAZUMEVANI
            self.microphone_popup.removeAllItems()
            self.microphone_popup.addItemsWithTitles_(
                [MIKROFON_PODRAZUMEVANI, *audio.input_devices()]
            )
            self.microphone_popup.selectItemWithTitle_(selected)

        self._accessibility_ok = hotkey.accessibility_granted()
        self._mikrofon_ok = audio.microphone_granted()

        with self.app._hist_lock:
            history = list(self.app._history)
        self._history_len = len(history)
        for index, view in enumerate(self.history_buttons):
            if index < len(history):
                short = " ".join(history[index].split())
                view.setTitle_(f"  {index + 1}. {short[:80]}")

        for key, view in self.controls.items():
            if key in ("transcription_provider", "text_model", "input_device", "mode"):
                continue
            if key == "text_style_written":
                value = self.app.cfg.get("text_style") == "written"
            elif key == "lokalna_pravila":
                value = self._lokalna_ukljucena()
            elif key == "ai_obrada":
                value = config.ai_obrada(self.app.cfg)
            else:
                value = self.app.cfg.get(key, False)
            if hasattr(view, "setState_"):
                view.setState_(
                    AppKit.NSControlStateValueOn if bool(value)
                    else AppKit.NSControlStateValueOff
                )

        if self.recorded_label is not None:
            self.recorded_label.setStringValue_(
                f"Ukupno snimljeno: {trajanje(self.app._recorded_seconds())}"
            )

        for page in self.pages:
            page.relayout()

    def refresh_recording(self):
        if self.stop_button is not None:
            active = self.app._recorder is not None or bool(self.app._starting)
            self.stop_button.setHidden_(not active)
