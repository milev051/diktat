"""Compact English settings for the macOS dictation app."""

import objc
import time
import AppKit
from Foundation import NSAttributedString, NSMakeRect, NSMakeSize

from . import audio, config, hotkey
from .upis import VELICINA_ISTORIJE


# Naziv izvora transkripcije stoji na JEDNOM mestu: iz njega se pravi spisak u
# prozoru, iz njega se cita nazad izabrana stavka. Dva spiska bi se razisla cim
# se doda treci izvor — bas to se i desilo kad su dosli Gemini modeli.
PROVIDER_TITLES = {
    "google": "Google Speech-to-Text",
    "gemini_live": "Gemini 3.5 Transcribe Live",
}

MIKROFON_PODRAZUMEVANI = "System default"

COLUMN = 248.0        # uska kolona: natpis miša i Quit stanu u jedan red
KOLONA_RAZMAK = 44.0  # razmak izmedju kolona
IVICA = 12.0          # margina prozora levo, desno i dole
DNO_RAZMAK = 6.0      # razmak izmedju dugmeta miša i Quit
QUIT_SIRINA = 68.0    # Quit je kratak; ostatak reda ostaje dugmetu miša
ZAGLAVLJE = 12.0     # visina reda sa dugmadima i ukupnim vremenom
GAP = 4.0             # razmak izmedju dve kontrole
SECTION_GAP = 14.0    # razmak PRE naslova grupe
SACUVANI_REDOVA = 3   # koliko sacuvanih snimaka se nudi za prepis
ISTORIJA_VIDLJIVIH = 5
ISTORIJA_VISINA_REDA = 32.0
HISTORY_PADDING = 10.0
NASLOV_MENIJA = "Diktat"  # po njemu se prepoznaje nas glavni meni
TITLE_GAP = 6.0      # razmak izmedju naslova grupe i prve kontrole
KVK_ESCAPE = 0x35     # Esc zatvara prozor; tokom snimanja prečice je briše


def mouse_button_title(cfg):
    if cfg.get("mouse_swipe"):
        return f"Mouse: {str(cfg['mouse_swipe']).capitalize()}"
    vk = cfg.get("mouse_key_vk")
    if isinstance(vk, int):
        return "Mouse: " + hotkey.NAZIVI_TASTERA.get(vk, f"Key {vk}")
    button = cfg.get("mouse_button")
    if button is not None:
        return "Mouse: Middle" if button == 2 else f"Mouse: Button {button + 1}"
    return "Record mouse button"


def left_button_title(button, title, inset=0.0):
    """Leva ivica natpisa ostaje ista i za kratak i za dugačak tekst.

    `setTitle_` na NSButton-u crta natpis po sredini čim se širina dugmeta
    razlikuje od širine teksta. Atributivni stil to fiksira posle svake izmene.
    `inset` uvlači natpis da ostane unutar okvira dugmeta.
    """
    style = AppKit.NSMutableParagraphStyle.alloc().init()
    style.setAlignment_(AppKit.NSTextAlignmentLeft)
    style.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
    if inset:
        style.setFirstLineHeadIndent_(inset)
        style.setHeadIndent_(inset)
        style.setTailIndent_(-inset)
    button.setTitle_(title)
    button.setAlignment_(AppKit.NSTextAlignmentLeft)
    button.setImagePosition_(AppKit.NSNoImage)
    try:
        cell = button.cell()
        cell.setAlignment_(AppKit.NSTextAlignmentLeft)
        cell.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
    except Exception:  # noqa: BLE001 — starija ćelija i dalje ima atributivni natpis
        pass
    button.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
        title, {
            AppKit.NSFontAttributeName: button.font() or AppKit.NSFont.systemFontOfSize_(13),
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.labelColor(),
            AppKit.NSParagraphStyleAttributeName: style,
        },
    ))


def provider_from_title(title: str) -> str:
    """Izabrana stavka -> kljuc podesavanja; nepoznato pada na Google."""
    for ime, naslov in PROVIDER_TITLES.items():
        if naslov == title:
            return ime
    return "google"


class _FlippedView(AppKit.NSView):
    """Pogled kome je nula GORE.

    Bez ovoga AppKit racuna od dna: kartica kraca od prozora zalepi se za dno,
    pa iznad sadrzaja stoji prazna polovina ekrana.
    """

    def isFlipped(self):  # noqa: N802 - ime trazi AppKit
        return True


class _Prozor(AppKit.NSWindow):
    """Prozor koji sam zna za Esc i za ⌘C/⌘V/⌘X/⌘A/⌘Z u poljima.

    Glavni meni (`_glavni_meni`) vezuje prečice za polja. Zatvaranje je Esc ili
    dugme X, ne ⌘W i ne gubitak fokusa.
    """

    PRECICE = {"c": "copy:", "v": "paste:", "x": "cut:",
               "a": "selectAll:", "z": "undo:"}

    def performKeyEquivalent_(self, event):  # noqa: N802 - ime trazi AppKit
        maska = event.modifierFlags() & AppKit.NSEventModifierFlagDeviceIndependentFlagsMask
        taster = (event.charactersIgnoringModifiers() or "").lower()
        if maska == AppKit.NSEventModifierFlagCommand and taster == "w":
            return True
        if maska == AppKit.NSEventModifierFlagCommand and taster in self.PRECICE:
            akcija = self.PRECICE[taster]
            if AppKit.NSApplication.sharedApplication().sendAction_to_from_(akcija, None, self):
                return True
        return objc.super(_Prozor, self).performKeyEquivalent_(event)

    def sendEvent_(self, event):  # noqa: N802 - ime trazi AppKit
        # Esc zatvara prozor i dok je kursor u polju: polje bi ga inace
        # progutalo kao „dopuni rec" i prozor ne bi ni saznao za njega.
        if (event.type() == AppKit.NSEventTypeKeyDown and event.keyCode() == KVK_ESCAPE
                and not event.modifierFlags()
                & AppKit.NSEventModifierFlagDeviceIndependentFlagsMask):
            owner = getattr(self, "settings_owner", None)
            if owner is not None and (getattr(owner.app, "_mouse_learning", False)
                    or time.monotonic() - getattr(owner.app, "_mouse_escape_at", 0) < 0.5):
                owner.app.listener.otkazi_snimanje()
                owner.app._dugme_misa_snimljeno(None, None)
                return
            self.performClose_(None)
            return
        objc.super(_Prozor, self).sendEvent_(event)


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
    """Jedan red kolone.

    `vidljivo` kaze da li opcija trenutno ima smisla. Opcija koja nema smisla
    ostaje na mestu, zatamnjena i neaktivna, da se vidi sta sve postoji. Samo
    redovi sa `sakrij` (upozorenja, istorija, sacuvani snimci) stvarno nestaju.
    """

    __slots__ = ("view", "height", "gap", "inset", "width", "vidljivo", "sakrij", "alpha")

    def __init__(self, view, height, gap, inset, width, vidljivo, sakrij=False):
        self.view = view
        self.height = height
        self.gap = gap
        self.inset = inset
        self.width = width
        self.vidljivo = vidljivo
        self.sakrij = sakrij
        self.alpha = float(view.alphaValue()) if view is not None else 1.0

    def prikazi(self) -> bool:
        return True if self.vidljivo is None else bool(self.vidljivo())


class _Page:
    """Jedna kolona: redovi se slazu odozgo nadole, visina se racuna sama."""

    def __init__(self):
        self.column = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, COLUMN, 10))
        self.rows: list[_Row] = []
        self.visina = 0.0

    def place(self, view, height, gap=GAP, inset=0.0, vidljivo=None, sakrij=False):
        self.column.addSubview_(view)
        self.rows.append(_Row(view, height, gap, inset, COLUMN - inset, vidljivo, sakrij))
        return view

    def place_left(self, view, height, width, gap=GAP, inset=0.0, vidljivo=None,
                   sakrij=False):
        """Kontrola prirodne sirine (dugme), poravnata levo."""
        self.column.addSubview_(view)
        self.rows.append(_Row(view, height, gap, inset, width, vidljivo, sakrij))
        return view

    def space(self, amount=SECTION_GAP, vidljivo=None, sakrij=False):
        """Prazan razmak; nestaje samo zajedno sa grupom koja se sklanja."""
        self.rows.append(_Row(None, amount, 0.0, 0.0, 0.0, vidljivo, sakrij))

    def relayout(self) -> float:
        y = 0.0
        for row in self.rows:
            prikazan = row.prikazi()
            if row.view is None:
                if (prikazan or not row.sakrij) and y > 0:
                    y += row.height
                continue
            if row.sakrij:
                row.view.setHidden_(not prikazan)
                if not prikazan:
                    continue
            else:
                _omoguci(row.view, prikazan, row.alpha)
            row.view.setFrame_(NSMakeRect(row.inset, y, row.width, row.height))
            y += row.height + row.gap
        self.visina = y
        self.column.setFrameSize_(NSMakeSize(COLUMN, y))
        return y


class SettingsWindow:
    """One column that resizes to the visible controls."""

    WIDTH = COLUMN + 2 * IVICA

    def __init__(self, app):
        self.app = app
        self.window = None
        self.pages = []
        self.document = None
        self.delegate = None
        self.controls = {}
        self.history_buttons = []
        self.history_scroll = None
        self.history_document = None
        self._history_row = None
        self._history_prvi = None
        self.microphone_popup = None
        self.stop_button = None
        self.quit_button = None
        self.update_header = None
        self.saved_rows = []
        self._sacuvani = []
        self.prepis_label = None
        self.mis_label = None
        self.dividers = []
        self._history_len = 0
        self._accessibility_ok = True
        self._mikrofon_ok = True

    # ------------------------------------------------------------ gradnja

    def show(self):
        if self.window is None:
            self._build()
        else:
            self.refresh()
        self._centriraj()
        self._activate()

    def _centriraj(self):
        """Tacno na sredinu ekrana, pri svakom otvaranju.

        `NSWindow.center` namerno stavlja prozor malo iznad sredine, a pomeren
        prozor bi se sledeci put otvorio tamo gde je ostavljen.
        """
        ekran = AppKit.NSScreen.mainScreen() or self.window.screen()
        if ekran is None:
            return
        polje = ekran.visibleFrame()
        okvir = self.window.frame()
        x = polje.origin.x + (polje.size.width - okvir.size.width) / 2
        y = polje.origin.y + (polje.size.height - okvir.size.height) / 2
        self.window.setFrameOrigin_(AppKit.NSMakePoint(round(x), round(y)))

    def hide(self):
        """Drugi klik na ikonicu sklanja prozor."""
        if self.window is not None:
            self.window.performClose_(None)

    def visible(self) -> bool:
        return self.window is not None and bool(self.window.isVisible())

    def pripremi(self):
        """Napravi prozor unapred, da prvi klik na ikonicu ne ceka gradnju."""
        if self.window is None:
            self._build()

    def _activate(self):
        nsapp = AppKit.NSApplication.sharedApplication()
        _glavni_meni(nsapp, self.app)
        nsapp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        self.window.makeKeyAndOrderFront_(None)
        nsapp.activateIgnoringOtherApps_(True)

    def _build(self):
        masks = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
        )
        self.window = _Prozor.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, self.WIDTH, 600),
            masks,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Speech to Text")
        self.window.settings_owner = self
        self.window.setReleasedWhenClosed_(False)
        # Svoje mesto u Mission Control-u: bez ovoga se prozor menu-bar
        # aplikacije ponasa kao pomocni panel iznad tudjeg prozora.
        self.window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorManaged)
        self.delegate = _WindowDelegate.alloc().initWithOwner_(self)
        self.window.setDelegate_(self.delegate)
        # Prozor ostaje i kad aplikacija izgubi fokus. Zatvara ga Esc ili X.

        # Skrol postoji samo za ekran nizi od sadrzaja; inace se ne vidi.
        scroll = AppKit.NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, self.WIDTH, 600))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setBorderType_(AppKit.NSNoBorder)
        scroll.setDrawsBackground_(False)
        self.document = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, self.WIDTH, 600))
        scroll.setDocumentView_(self.document)
        self.window.setContentView_(scroll)

        self.pages = [self._kolona_podesavanja()]
        page = self.pages[0]
        page.column.setFrameOrigin_(AppKit.NSMakePoint(IVICA, ZAGLAVLJE))
        self.document.addSubview_(page.column)

        self.refresh()
        self.refresh_recording()
        self._centriraj()

    def _rasporedi(self):
        """Visina prozora prati najvisu kolonu; gornja ivica ostaje gde je."""
        kolone = max(page.relayout() for page in self.pages)
        for linija in self.dividers:
            okvir_linije = linija.frame()
            linija.setFrame_(NSMakeRect(okvir_linije.origin.x, ZAGLAVLJE, 1, kolone))
        visina = ZAGLAVLJE + kolone + IVICA
        self.document.setFrameSize_(NSMakeSize(self.WIDTH, visina))
        ekran = self.window.screen() or AppKit.NSScreen.mainScreen()
        if ekran is not None:
            visina = min(visina, ekran.visibleFrame().size.height - 40.0)
        okvir = self.window.frame()
        novi = self.window.frameRectForContentRect_(NSMakeRect(0, 0, self.WIDTH, visina))
        if abs(novi.size.height - okvir.size.height) < 0.5:
            return
        vrh = okvir.origin.y + okvir.size.height
        self.window.setFrame_display_(
            NSMakeRect(okvir.origin.x, vrh - novi.size.height,
                       novi.size.width, novi.size.height),
            True,
        )

    # ------------------------------------------------------------- uslovi

    def _provider(self) -> str:
        return self.app.cfg.get("transcription_provider", "google")

    def _samo_za(self, *imena):
        """Uslov: red se vidi samo uz navedene izvore transkripcije."""
        return lambda: self._provider() in imena

    def _dozvole_ok(self) -> bool:
        return self._accessibility_ok and self._mikrofon_ok

    # ----------------------------------------------------------- kartice

    def _kolona_podesavanja(self) -> _Page:
        page = _Page()
        self._checkbox(page, "Lowercase", "lowercase", True)
        self._checkbox(page, "Remove diacritics", "ascii_diacritics", False)
        self._checkbox(page, "Abbreviations", "abbreviations", True)
        self._checkbox(page, "Start at login", "start_at_login", True)
        self._popup(page, "Microphone", "input_device",
                    [MIKROFON_PODRAZUMEVANI, *audio.input_devices()],
                    self.app.cfg.get("input_device") or MIKROFON_PODRAZUMEVANI)
        self.microphone_popup = self.controls["input_device"]
        self._popup(page, "Service", "transcription_provider", list(PROVIDER_TITLES.values()),
                    PROVIDER_TITLES.get(self._provider(), PROVIDER_TITLES["gemini_live"]))
        live = self._samo_za("gemini_live")
        self._gemini_key_field(page, live)

        self._button(page, "Open Accessibility settings", "accessibility",
                     vidljivo=lambda: not self._accessibility_ok, sakrij=True)
        self._button(page, "Open Microphone settings", "microphone",
                     vidljivo=lambda: not self._mikrofon_ok, sakrij=True)
        self._history_list(page)
        self._dno(page)
        return page

    def _dno(self, page):
        """Miš i Quit u jednom redu: miš uzima preostalu širinu, Quit desno."""
        self.mouse_button = self._plain_button("Record mouse button", "mouse_learn")
        self.mouse_button.setBordered_(True)
        self.mouse_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        left_button_title(self.mouse_button, "Record mouse button", inset=2)
        self.quit_button = self._plain_button("Quit", "quit")
        row = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, COLUMN, 30))
        mouse_w = COLUMN - QUIT_SIRINA - DNO_RAZMAK
        self.mouse_button.setFrame_(NSMakeRect(0, 0, mouse_w, 30))
        self.quit_button.setFrame_(NSMakeRect(mouse_w + DNO_RAZMAK, 0, QUIT_SIRINA, 30))
        row.addSubview_(self.mouse_button)
        row.addSubview_(self.quit_button)
        page.place(row, 30)

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

    def _section(self, page, title, description="", vidljivo=None, sakrij=False):
        page.space(vidljivo=vidljivo, sakrij=sakrij)
        page.place(self._plain_label(title, 15, bold=True), 22,
                   gap=(4.0 if description else TITLE_GAP), vidljivo=vidljivo,
                   sakrij=sakrij)
        if description:
            self._hint(page, description, gap=TITLE_GAP, vidljivo=vidljivo, sakrij=sakrij)

    def _hint(self, page, text, gap=GAP, inset=0.0, vidljivo=None, sakrij=False):
        field = self._plain_label(text, 12, alpha=0.6)
        visina = self._text_height(field, COLUMN - inset, 17.0)
        return page.place(field, visina, gap=gap, inset=inset, vidljivo=vidljivo,
                          sakrij=sakrij)

    def _plain_button(self, title, identifier):
        item = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 30))
        item.setTitle_(title)
        item.setBezelStyle_(AppKit.NSBezelStyleRounded)
        item.setTarget_(self.app)
        item.setAction_("settingsButton:")
        item.setIdentifier_(identifier)
        return item

    def _button(self, page, title, identifier, full_width=False, vidljivo=None,
                sakrij=False):
        item = self._plain_button(title, identifier)
        if full_width:
            # Redovi istorije nose ceo tekst, pa idu preko cele kolone i
            # poravnati su levo — centriran dugacak prepis se cita gore.
            try:
                item.cell().setAlignment_(AppKit.NSTextAlignmentLeft)
            except Exception:      # noqa: BLE001
                pass
            return page.place(item, 26, gap=4.0, vidljivo=vidljivo, sakrij=sakrij)
        item.sizeToFit()
        sirina = min(COLUMN, max(item.frame().size.width + 28, 150.0))
        return page.place_left(item, 30, sirina, gap=4.0, vidljivo=vidljivo,
                               sakrij=sakrij)

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
        control = page.place(item, 20, gap=4.0, inset=inset, vidljivo=vidljivo)
        self.controls[key] = control
        return control

    def _popup(self, page, title, key, values, selected, vidljivo=None):
        item = AppKit.NSPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 26))
        item.setAccessibilityLabel_(title)
        item.addItemsWithTitles_(values)
        if selected in values:
            item.selectItemWithTitle_(selected)
        item.setTarget_(self.app)
        item.setAction_("settingsPopup:")
        item.setIdentifier_(key)
        control = page.place(item, 26, vidljivo=vidljivo)
        self.controls[key] = control
        return control

    def _field(self, page, title, key, secure=False, vidljivo=None, sakrij=False):
        page.place(self._plain_label(title, 12, alpha=0.6), 16, gap=2.0,
                   vidljivo=vidljivo, sakrij=sakrij)
        cls = AppKit.NSSecureTextField if secure else AppKit.NSTextField
        item = cls.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 24))
        item.setStringValue_(str(self.app.cfg.get(key, "")))
        item.setIdentifier_(key)
        item.setDelegate_(self.app)
        control = page.place(item, 24, gap=10.0, vidljivo=vidljivo, sakrij=sakrij)
        self.controls[key] = control
        return control

    def _gemini_key_field(self, page, visible):
        row = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, COLUMN, 26))
        field = AppKit.NSSecureTextField.alloc().initWithFrame_(
            NSMakeRect(0, 1, COLUMN - 36, 24))
        field.setStringValue_(str(self.app.cfg.get("polish_api_key", "")))
        field.setAccessibilityLabel_("Gemini API key")
        field.setIdentifier_("polish_api_key")
        field.setDelegate_(self.app)
        row.addSubview_(field)
        self.controls["polish_api_key"] = field
        self.api_check_button = self._plain_button("✓", "check_api")
        self.api_check_button.setFrame_(NSMakeRect(COLUMN - 30, 0, 30, 26))
        self.api_check_button.setToolTip_("Check Gemini key")
        row.addSubview_(self.api_check_button)
        page.place(row, 26, vidljivo=visible, sakrij=True)
        self.api_key_row = row

    def refresh_api_check(self):
        button = getattr(self, "api_check_button", None)
        if button is None:
            return
        checking = getattr(self.app, "_api_check_running", False)
        status = getattr(self.app, "_api_check_status", "")
        valid = status == "Gemini: API key works"
        title = "…" if checking else ("✓" if valid or not status else "×")
        color = (AppKit.NSColor.secondaryLabelColor() if checking or not status
                 else AppKit.NSColor.systemGreenColor() if valid
                 else AppKit.NSColor.systemRedColor())
        button.setTitle_(title)
        button.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
            title, {AppKit.NSForegroundColorAttributeName: color}))
        button.setToolTip_("Checking Gemini key…" if checking else status or "Check Gemini key")

    def _history_list(self, page):
        """Pet vidljivih redova; do sto prepiski skroluje se unutar liste."""
        scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, COLUMN, ISTORIJA_VIDLJIVIH * ISTORIJA_VISINA_REDA)
        )
        scroll.setHasVerticalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setBorderType_(AppKit.NSBezelBorder)
        scroll.setDrawsBackground_(False)
        document = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, COLUMN, 10))
        scroll.setDocumentView_(document)
        for index in range(VELICINA_ISTORIJE):
            item = self._plain_button("", f"copy_history_{index}")
            item.setBordered_(False)
            left_button_title(item, "")
            item.setHidden_(True)
            document.addSubview_(item)
            self.history_buttons.append(item)
        self.history_scroll = scroll
        self.history_document = document
        page.place(
            scroll, ISTORIJA_VIDLJIVIH * ISTORIJA_VISINA_REDA, gap=4.0,
            vidljivo=lambda: self._history_len > 0, sakrij=True,
        )
        self._history_row = page.rows[-1]

    def _osvezi_istoriju(self, history):
        if self.history_scroll is None:
            return
        document_width = COLUMN - 2.0
        sirina = max(80.0, document_width - 2 * HISTORY_PADDING)
        for index, view in enumerate(self.history_buttons):
            if index < len(history):
                short = " ".join(history[index].split())
                left_button_title(view, f"{index + 1}. {short}")
                view.setHidden_(False)
                view.setFrame_(NSMakeRect(HISTORY_PADDING, HISTORY_PADDING + index * ISTORIJA_VISINA_REDA, sirina, 26))
            else:
                view.setHidden_(True)
        self.history_document.setFrameSize_(NSMakeSize(
            document_width, 2 * HISTORY_PADDING + max(ISTORIJA_VISINA_REDA, len(history) * ISTORIJA_VISINA_REDA),
        ))
        if self._history_row is not None:
            vidljivih = min(ISTORIJA_VIDLJIVIH, len(history))
            self._history_row.height = vidljivih * ISTORIJA_VISINA_REDA + 2 * HISTORY_PADDING
        prvi = history[0] if history else ""
        if prvi != self._history_prvi:
            self._history_prvi = prvi
            clip = self.history_scroll.contentView()
            if clip is not None:
                clip.scrollToPoint_(AppKit.NSMakePoint(0, 0))
                self.history_scroll.reflectScrolledClipView_(clip)

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

        history = self.app.upis.istorija()
        self._history_len = len(history)
        self._osvezi_istoriju(history)

        for key, view in self.controls.items():
            if key in ("transcription_provider", "text_model", "input_device", "mode"):
                continue
            if key == "strip_punctuation":
                value = self.app.cfg.get("strip_punctuation", True)
            elif key == "punctuation":
                value = not self.app.cfg.get("strip_punctuation", True)
            else:
                value = self.app.cfg.get(key, False)
            if hasattr(view, "setState_"):
                view.setState_(
                    AppKit.NSControlStateValueOn if bool(value)
                    else AppKit.NSControlStateValueOff
                )

        if getattr(self, "mouse_button", None) is not None:
            left_button_title(
                self.mouse_button,
                self.app.mis_status or mouse_button_title(self.app.cfg),
                inset=2,
            )
        self.refresh_transcription_status()

        self.refresh_api_check()

        self._rasporedi()

    def refresh_recording(self):
        self.refresh_transcription_status()
        if self.stop_button is not None:
            active = self.app._recorder is not None or bool(self.app._starting)
            if bool(self.stop_button.isEnabled()) != active:
                self.stop_button.setEnabled_(active)

    def refresh_transcription_status(self):
        label = getattr(self, "transcription_status_label", None)
        if label is not None:
            status = self.app.last_transcription_status
            if self.app._recorder is not None and getattr(self.app, "_live_waiting", False):
                status = "Prepis uživo kasni; mikrofon nastavlja da snima."
            label.setStringValue_(status)
            detail = self.app.last_transcription_detail or "Nema zabeleženih grešaka."
            if self.transcription_detail_label.stringValue() != detail:
                self.transcription_detail_label.setStringValue_(detail)
                self.transcription_detail_row.height = self._text_height(
                    self.transcription_detail_label, COLUMN, 17,
                )
                self._rasporedi()


def _zeleno(dugme, ukljuceno=True):
    """Zeleno dugme znaci da ima nove verzije, kao na telefonu.

    Zelena je pozadina, a natpis beo i podebljan. Zelen natpis se na zelenoj
    pozadini nije video (22.09.2026); beo se cita i kad je prozor neaktivan,
    pa pozadina posivi.
    """
    if hasattr(dugme, "setBezelColor_"):
        dugme.setBezelColor_(AppKit.NSColor.systemGreenColor() if ukljuceno else None)
    if ukljuceno:
        stil = AppKit.NSMutableParagraphStyle.alloc().init()
        stil.setAlignment_(AppKit.NSTextAlignmentCenter)
        dugme.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
            dugme.title(), {
                AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
                AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(13),
                AppKit.NSParagraphStyleAttributeName: stil,
            }))


class _MeniAplikacije(AppKit.NSObject):
    """Stavka menija mora da ima AppKit cilj, rumps objekat to nije."""

    def initWithApp_(self, app):
        self = objc.super(_MeniAplikacije, self).init()
        if self is not None:
            self._app = app
        return self

    def ponovoPokreni_(self, _sender):  # noqa: N802 - ime trazi AppKit
        self._app.ponovo_pokreni()


def _glavni_meni(nsapp, app=None):
    """Prečice koje svaki prozor ima: ⌘C/⌘V/⌘X/⌘A/⌘Z u poljima.

    Menu-bar aplikacija nema glavni meni, a macOS prečice ne vezuje za prozor
    nego za stavke tog menija. Bez njega ⌘V ne lepi ključ u polje. Stavke nemaju
    cilj (`target`), pa idu prvom koji ume da ih izvrši: polju u fokusu.
    Prozor se ne zatvara sa ⌘W.
    """
    # macOS sam napravi podrazumevani meni („Python", jedna stavka) cim
    # aplikacija postane obicna, pa „meni vec postoji" ne znaci da je nas.
    postojeci = nsapp.mainMenu()
    if postojeci is not None and postojeci.title() == NASLOV_MENIJA:
        return
    glavni = AppKit.NSMenu.alloc().initWithTitle_(NASLOV_MENIJA)

    def podmeni(naslov, stavke):
        nosac = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(naslov, None, "")
        meni = AppKit.NSMenu.alloc().initWithTitle_(naslov)
        for tekst, akcija, taster in stavke:
            meni.addItem_(AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                tekst, akcija, taster))
        nosac.setSubmenu_(meni)
        glavni.addItem_(nosac)

    podmeni("Diktat", [("Close window", "performClose:", "")])
    if app is not None:
        meni_diktat = glavni.itemAtIndex_(0).submenu()
        meni_diktat.addItem_(AppKit.NSMenuItem.separatorItem())
        stavka = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Restart", "ponovoPokreni:", "")
        if getattr(app, "_meni_delegate", None) is None:
            app._meni_delegate = _MeniAplikacije.alloc().initWithApp_(app)
        stavka.setTarget_(app._meni_delegate)
        meni_diktat.addItem_(stavka)
    podmeni("Edit", [
        ("Undo", "undo:", "z"),
        ("Cut", "cut:", "x"),
        ("Copy", "copy:", "c"),
        ("Paste", "paste:", "v"),
        ("Select all", "selectAll:", "a"),
    ])
    nsapp.setMainMenu_(glavni)


def _omoguci(view, ukljuceno: bool, alpha: float):
    """Opcija bez smisla ostaje vidljiva, ali zatamnjena i neaktivna."""
    view.setHidden_(False)
    natpis = isinstance(view, AppKit.NSTextField) and not view.isEditable()
    if isinstance(view, AppKit.NSControl) and not natpis:
        view.setEnabled_(ukljuceno)
    view.setAlphaValue_(alpha if ukljuceno else alpha * 0.4)
