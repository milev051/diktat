"""Mala obojena pilula koja pokazuje stanje diktata.

Bez teksta i bez ikonice — boja pozadine je citav indikator:

    zeleno       snima      sadrzaj: proteklo vreme
    zuto         obradjuje  sadrzaj: vreme zamrznuto na kraju snimanja
    narandzasto  greska     sadrzaj: poruka

Panel je `NSWindowStyleMaskNonactivatingPanel` i nikad ne preuzima fokus —
to je bitno jer se prepoznat tekst na kraju lepi u aplikaciju koja je bila
aktivna pre diktata.

Dve stvari koje nisu ocigledne:

  * Okvir labele mora da bude siri od izmerene sirine teksta. `sizeWithAttributes_`
    zaokruzuje nanize, a `NSLineBreakByTruncatingHead` onda odsece POCETAK i
    zalepi "…" — pa "snimam" postane "…imam".

  * Pozadina je obican sloj sa `cornerRadius`, ne `NSVisualEffectView`. Za
    zamucenu pozadinu je bila potrebna `maskImage` jer `masksToBounds` ne
    sece backdrop koji crta window server; sa punom bojom to otpada.

Svi metodi se smeju zvati SAMO sa glavne niti (rumps Timer je na njoj).
"""

import math

import AppKit
import objc
import Quartz
from Foundation import NSMakeRect

HEIGHT = 34.0
PAD_X = 16.0
MIN_WIDTH = 74.0
MAX_WIDTH = 640.0
SLACK = 3.0              # rezerva da se tekst nikad ne odseca
RING_WIDTH = 3.0         # zuti prsten kad se nesto obradjuje u pozadini
MONO_TEMPLATE = "99s left"   # najsiri sadrzaj tajmera; po njemu je fiksna sirina

BOTTOM_MARGIN = 150      # za position="bottom"
EDGE_MARGIN = 12         # za position="top-right"

# stanje -> (pozadina, boja teksta)
STATES = {
    "recording": ((0.11, 0.57, 0.24), (1.00, 1.00, 1.00)),
    "processing": ((1.00, 0.76, 0.03), (0.14, 0.11, 0.02)),
    "error": ((0.82, 0.31, 0.02), (1.00, 1.00, 1.00)),
    "done": ((0.11, 0.57, 0.24), (1.00, 1.00, 1.00)),
}
STATES["thinking"] = STATES["processing"]


def _cgcolor(rgb):
    return Quartz.CGColorCreateGenericRGB(rgb[0], rgb[1], rgb[2], 1.0)


def _nscolor(rgb):
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], 1.0)


class Overlay:
    def __init__(self, position="bottom"):
        self.position = position if position in ("bottom", "top-right") else "bottom"
        self._panel = None
        self._pill = None
        self._label = None
        self._visible = False
        self._state = "recording"
        self._fixed_mono_w = None
        self._busy = False
        self._mono_font = AppKit.NSFont.monospacedSystemFontOfSize_weight_(
            14, AppKit.NSFontWeightSemibold
        )
        self._text_font = AppKit.NSFont.systemFontOfSize_weight_(
            14, AppKit.NSFontWeightMedium
        )

    # ------------------------------------------------------------------

    def _build(self):
        if self._panel is not None:
            return

        style = (
            AppKit.NSWindowStyleMaskBorderless
            | AppKit.NSWindowStyleMaskNonactivatingPanel
        )
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, MIN_WIDTH, HEIGHT),
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(AppKit.NSScreenSaverWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )

        pill = AppKit.NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, MIN_WIDTH, HEIGHT)
        )
        pill.setWantsLayer_(True)
        pill.layer().setCornerRadius_(HEIGHT / 2)
        pill.layer().setBackgroundColor_(_cgcolor(STATES["recording"][0]))
        panel.setContentView_(pill)

        label = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(PAD_X, 0, MIN_WIDTH - PAD_X * 2, HEIGHT)
        )
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(self._mono_font)
        label.setTextColor_(_nscolor(STATES["recording"][1]))
        label.setAlignment_(AppKit.NSTextAlignmentCenter)
        label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingHead)
        label.setUsesSingleLineMode_(True)
        label.setMaximumNumberOfLines_(1)
        label.setStringValue_("")
        pill.addSubview_(label)

        self._panel = panel
        self._pill = pill
        self._label = label

    # ------------------------------------------------------------------

    def _measure(self, text, font) -> float:
        attrs = {AppKit.NSFontAttributeName: font}
        return AppKit.NSString.stringWithString_(text or " ").sizeWithAttributes_(
            attrs
        ).width

    def _origin(self, width):
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            return None
        v = screen.visibleFrame()
        if self.position == "top-right":
            # visibleFrame vec iskljucuje menu bar, pa je ovo tacno ispod njega.
            return (
                v.origin.x + v.size.width - width - EDGE_MARGIN,
                v.origin.y + v.size.height - HEIGHT - EDGE_MARGIN,
            )
        return (
            v.origin.x + (v.size.width - width) / 2,
            v.origin.y + BOTTOM_MARGIN,
        )

    def _mono_width(self) -> float:
        """Fiksna sirina za tajmer.

        Sadrzaj je uvek nekoliko cifara, pa nema razloga da se pilula siri i
        skuplja — meri se jednom po najsirem mogucem tekstu i tu ostaje.
        """
        if self._fixed_mono_w is None:
            self._fixed_mono_w = (
                math.ceil(self._measure(MONO_TEMPLATE, self._mono_font)) + SLACK
            )
        return self._fixed_mono_w

    def _layout(self, text, mono):
        font = self._mono_font if mono else self._text_font
        if self._label.font() is not font:
            self._label.setFont_(font)

        if mono:
            text_w = self._mono_width()
        else:
            text_w = math.ceil(self._measure(text, font)) + SLACK
        width = min(MAX_WIDTH, max(MIN_WIDTH, text_w + PAD_X * 2))

        line_h = font.ascender() - font.descender()
        self._label.setFrame_(
            NSMakeRect(PAD_X, (HEIGHT - line_h) / 2, width - PAD_X * 2, line_h)
        )

        origin = self._origin(width)
        if origin is None:
            return
        x, y = origin
        current = self._panel.frame()
        if abs(current.size.width - width) > 0.5 or abs(current.origin.x - x) > 0.5:
            self._panel.setFrame_display_(NSMakeRect(x, y, width, HEIGHT), True)
            self._pill.setFrame_(NSMakeRect(0, 0, width, HEIGHT))

    # ------------------------------------------------------------------

    def show(self, text="", mono=True):
        self._build()
        self._label.setStringValue_(text)
        self._layout(text, mono)
        self._panel.orderFrontRegardless()
        self._visible = True

    def set_text(self, text: str, mono=True):
        if self._label is None or not self._visible:
            return
        if self._label.stringValue() != text:
            self._label.setStringValue_(text)
            self._layout(text, mono)

    def set_state(self, state):
        if self._pill is None or state == self._state:
            return
        background, foreground = STATES.get(state, STATES["recording"])
        self._pill.layer().setBackgroundColor_(_cgcolor(background))
        self._label.setTextColor_(_nscolor(foreground))
        self._state = state

    def set_busy(self, busy: bool):
        """Zuti prsten oko zelene pilule: snima, a nesto se paralelno obradjuje.

        Bez ovoga se tokom snimanja uopste ne vidi da prethodni segment jos
        putuje — pilula je zelena i dok se u pozadini nesto obradjuje.
        """
        if self._pill is None or busy == self._busy:
            return
        layer = self._pill.layer()
        if busy:
            layer.setBorderWidth_(RING_WIDTH)
            layer.setBorderColor_(_cgcolor(STATES["processing"][0]))
        else:
            layer.setBorderWidth_(0.0)
        self._busy = busy

    def hide(self):
        self.set_busy(False)
        if self._panel is not None and self._visible:
            self._panel.orderOut_(None)
        self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible


# ---------------------------------------------------------------- prikaz uzivo

LIVE_MAX_WIDTH = 760.0
LIVE_MAX_HEIGHT = 260.0
LIVE_BOTTOM = 120.0
LIVE_CHARS = 400          # koliko poslednjih znakova stoji na ekranu
# Izgled titla: centriran tekst, iza svakog reda crna cetvrtasta traka 75 %.
TITL_FONT = 19.0
TITL_PAD_X = 10.0         # traka viri levo i desno od reda
TITL_PAD_Y = 4.0          # i iznad prvog, ispod poslednjeg reda
TITL_TRAKA = (0.0, 0.0, 0.0, 0.75)
TITL_TRAKA_KASNI = (1.00, 0.80, 0.05, 0.92)   # zuto: prepis kasni, mikrofon snima
PLACEHOLDER = "Listening…"


class TitlView(AppKit.NSView):
    """Crta tekst kao titl: svaki red na svojoj traci, bez okvira oko svega."""

    def initWithFrame_(self, frame):
        self = objc.super(TitlView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.storage = AppKit.NSTextStorage.alloc().init()
        self.lm = AppKit.NSLayoutManager.alloc().init()
        self.container = AppKit.NSTextContainer.alloc().initWithContainerSize_(
            AppKit.NSMakeSize(frame.size.width - 2 * TITL_PAD_X, 1e5)
        )
        self.container.setLineFragmentPadding_(0)
        self.lm.addTextContainer_(self.container)
        self.storage.addLayoutManager_(self.lm)
        self.traka = TITL_TRAKA
        self.visina_reda = 0.0
        return self

    def isFlipped(self):
        return True

    @objc.python_method
    def postavi(self, text, boja, font):
        stil = AppKit.NSMutableParagraphStyle.alloc().init()
        stil.setAlignment_(AppKit.NSTextAlignmentCenter)
        stil.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        # Razmak izmedju redova = gornji + donji luft trake, da se trake
        # dodiruju bez preklapanja i da svaki red ima isti luft gore i dole.
        stil.setLineSpacing_(2 * TITL_PAD_Y)
        self.visina_reda = self.lm.defaultLineHeightForFont_(font)
        attrs = {
            AppKit.NSFontAttributeName: font,
            AppKit.NSForegroundColorAttributeName: boja,
            AppKit.NSParagraphStyleAttributeName: stil,
        }
        self.storage.setAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        )
        self.setNeedsDisplay_(True)

    @objc.python_method
    def sirina_teksta(self, width):
        self.container.setContainerSize_(AppKit.NSMakeSize(width - 2 * TITL_PAD_X, 1e5))

    @objc.python_method
    def redovi(self):
        """Pravougaonik svakog reda (koriscen deo), odozgo nadole."""
        self.lm.ensureLayoutForTextContainer_(self.container)
        out = []
        i, n = 0, self.lm.numberOfGlyphs()
        while i < n:
            rect, opseg = self.lm.lineFragmentUsedRectForGlyphAtIndex_effectiveRange_(i, None)
            out.append((rect, opseg))
            i = opseg.location + opseg.length
        return out

    @objc.python_method
    def visina(self) -> float:
        redovi = self.redovi()
        if not redovi:
            return 0.0
        poslednji = redovi[-1][0]
        return math.ceil(poslednji.origin.y + self.visina_reda + 2 * TITL_PAD_Y)

    def drawRect_(self, dirty):
        redovi = self.redovi()
        if not redovi:
            return
        AppKit.NSColor.colorWithRed_green_blue_alpha_(*self.traka).set()
        for r, opseg in redovi:
            # Bez praznih razmaka na kraju reda, da traka bude simetricna.
            vidljiv = self.lm.boundingRectForGlyphRange_inTextContainer_(
                AppKit.NSMakeRange(opseg.location, opseg.length), self.container
            )
            x0 = r.origin.x + TITL_PAD_X - TITL_PAD_X
            sirina = r.size.width
            if vidljiv.size.width and vidljiv.size.width < sirina:
                sirina = vidljiv.size.width
                x0 = vidljiv.origin.x
            # Tekst reda pocinje na r.y + PAD_Y; traka ima PAD_Y luft gore i dole.
            AppKit.NSRectFill(NSMakeRect(
                x0, r.origin.y, sirina + 2 * TITL_PAD_X, self.visina_reda + 2 * TITL_PAD_Y
            ))
        self.lm.drawGlyphsForGlyphRange_atPoint_(
            AppKit.NSMakeRange(0, self.lm.numberOfGlyphs()),
            AppKit.NSMakePoint(TITL_PAD_X, TITL_PAD_Y),
        )


class LivePanel:
    """Okvir sa prepisom koji se ispisuje DOK govoris, u izgledu titla.

    Postoji zato sto direktan upis u aktivno polje stize tek kad Gemini potvrdi
    celinu. Ovde se vidi i medjurezultat, koji se u polje namerno NE kuca:
    model sme da ga promeni, pa bi kasnija izmena obrisala rucnu ispravku.

    Izgled (od 2026-11-13): centriran tekst, svaki red na crnoj cetvrtastoj
    traci od 75 %, kao titl. Kad prepis kasni, trake postaju zute, tekst crn.

    Panel je `NonactivatingPanel`, propusta klik i nikad ne uzima fokus, jer
    tekst mora da ode u polje koje je bilo aktivno pre diktata.
    Svi metodi se zovu SAMO sa glavne niti.
    """

    def __init__(self, avoid_pill=False):
        self.avoid_pill = avoid_pill
        self._panel = None
        self._view = None
        self._delayed = False
        self._visible = False
        self._text = ""
        self._font = AppKit.NSFont.systemFontOfSize_weight_(
            TITL_FONT, AppKit.NSFontWeightMedium
        )

    @property
    def visible(self) -> bool:
        return self._visible

    def _build(self):
        if self._panel is not None:
            return
        style = (
            AppKit.NSWindowStyleMaskBorderless
            | AppKit.NSWindowStyleMaskNonactivatingPanel
        )
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, LIVE_MAX_WIDTH, 40),
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(AppKit.NSScreenSaverWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setIgnoresMouseEvents_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )
        view = TitlView.alloc().initWithFrame_(NSMakeRect(0, 0, LIVE_MAX_WIDTH, 40))
        panel.setContentView_(view)
        self._panel = panel
        self._view = view

    def set_delayed(self, delayed: bool):
        """Prepis kasni: trake postaju zute, tekst crn, bez poruke."""
        delayed = bool(delayed)
        self._build()
        if delayed == self._delayed:
            return
        self._delayed = delayed
        self._view.traka = TITL_TRAKA_KASNI if delayed else TITL_TRAKA
        self._crtaj()

    def _boja_teksta(self):
        prazno = self._text in ("", PLACEHOLDER)
        if self._delayed:
            return AppKit.NSColor.colorWithWhite_alpha_(0.0, 0.6 if prazno else 0.95)
        return AppKit.NSColor.colorWithWhite_alpha_(1.0, 0.6 if prazno else 1.0)

    def _width(self) -> float:
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            return LIVE_MAX_WIDTH
        return min(LIVE_MAX_WIDTH, max(320.0, screen.visibleFrame().size.width - 160))

    def _height(self, text, width) -> float:
        """Visina svih redova sa trakama, ogranicena da ne pokrije ekran."""
        self._view.sirina_teksta(width)
        self._view.postavi(text or " ", self._boja_teksta(), self._font)
        return min(LIVE_MAX_HEIGHT, self._view.visina())

    def _crtaj(self):
        if not self._text:
            return
        width = self._width()
        height = self._height(self._text, width)
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            return
        v = screen.visibleFrame()
        # Kad je pilula sa vremenom takodje na dnu, titl ide iznad nje.
        dno = LIVE_BOTTOM + (HEIGHT + 14 if self.avoid_pill else 0)
        x = v.origin.x + (v.size.width - width) / 2
        y = v.origin.y + dno
        self._panel.setFrame_display_(NSMakeRect(x, y, width, height), True)
        self._view.setFrame_(NSMakeRect(0, 0, width, height))
        self._view.setNeedsDisplay_(True)

    # ------------------------------------------------------------------

    def show(self, text="", status=""):
        self._build()
        self.set_text(text, status=status)
        self._panel.orderFrontRegardless()
        self._visible = True

    def set_text(self, text, status=""):
        self._build()
        # Samo rep: dug diktat bi inace prerastao ekran, a gleda se ionako
        # poslednja recenica.
        clean = " ".join((text or "").split())[-(180 if status else LIVE_CHARS):]
        prikaz = (status + "\n\n" + (clean or PLACEHOLDER)) if status else (clean or PLACEHOLDER)
        if prikaz == self._text:
            return
        self._text = prikaz
        self._crtaj()

    def hide(self):
        if self._panel is not None and self._visible:
            self._panel.orderOut_(None)
        self._visible = False
        self._text = ""
        if self._view is not None:
            self.set_delayed(False)
