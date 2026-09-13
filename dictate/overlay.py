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
import Quartz
from Foundation import NSMakeRect

HEIGHT = 34.0
PAD_X = 16.0
MIN_WIDTH = 74.0
MAX_WIDTH = 640.0
SLACK = 3.0              # rezerva da se tekst nikad ne odseca
RING_WIDTH = 3.0         # zuti prsten kad se nesto obradjuje u pozadini
MONO_TEMPLATE = "još 99s"   # najsiri sadrzaj tajmera; po njemu je fiksna sirina

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
LIVE_MIN_HEIGHT = 46.0
LIVE_MAX_HEIGHT = 200.0
LIVE_PAD = 18.0
LIVE_BOTTOM = 120.0
LIVE_CHARS = 400          # koliko poslednjih znakova stoji na ekranu
LIVE_BG = (0.08, 0.09, 0.11)


class LivePanel:
    """Okvir sa prepisom koji se ispisuje DOK govoris.

    Postoji zato sto direktan upis u aktivno polje stize tek kad Gemini potvrdi
    celinu — izmedju dve potvrde nema nikakvog znaka da aplikacija cuje. Ovde se
    vidi i medjurezultat, koji se u polje namerno NE kuca: model sme da ga
    promeni, pa bi kasnija izmena obrisala rucnu ispravku.

    Panel je isti soj kao pilula: `NonactivatingPanel`, propusta klik i nikad ne
    uzima fokus, jer tekst mora da ode u polje koje je bilo aktivno pre diktata.
    Svi metodi se zovu SAMO sa glavne niti.
    """

    def __init__(self, avoid_pill=False):
        self.avoid_pill = avoid_pill
        self._panel = None
        self._box = None
        self._label = None
        self._visible = False
        self._text = ""
        self._font = AppKit.NSFont.systemFontOfSize_weight_(
            17, AppKit.NSFontWeightMedium
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
            NSMakeRect(0, 0, LIVE_MAX_WIDTH, LIVE_MIN_HEIGHT),
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

        box = AppKit.NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, LIVE_MAX_WIDTH, LIVE_MIN_HEIGHT)
        )
        box.setWantsLayer_(True)
        box.layer().setCornerRadius_(14.0)
        box.layer().setBackgroundColor_(
            Quartz.CGColorCreateGenericRGB(LIVE_BG[0], LIVE_BG[1], LIVE_BG[2], 0.92)
        )
        panel.setContentView_(box)

        label = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(LIVE_PAD, LIVE_PAD, LIVE_MAX_WIDTH - LIVE_PAD * 2, 20)
        )
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(self._font)
        label.setTextColor_(AppKit.NSColor.whiteColor())
        label.setAlignment_(AppKit.NSTextAlignmentLeft)
        label.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        label.setUsesSingleLineMode_(False)
        label.setMaximumNumberOfLines_(0)
        label.setStringValue_("")
        box.addSubview_(label)

        self._panel = panel
        self._box = box
        self._label = label

    def _width(self) -> float:
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            return LIVE_MAX_WIDTH
        return min(LIVE_MAX_WIDTH, max(320.0, screen.visibleFrame().size.width - 160))

    def _height(self, text, width) -> float:
        """Visina prelomljenog teksta, ogranicena da okvir ne pokrije ekran."""
        attrs = {AppKit.NSFontAttributeName: self._font}
        okvir = AppKit.NSString.stringWithString_(text or " ").boundingRectWithSize_options_attributes_(
            AppKit.NSMakeSize(width - LIVE_PAD * 2, LIVE_MAX_HEIGHT),
            AppKit.NSStringDrawingUsesLineFragmentOrigin
            | AppKit.NSStringDrawingUsesFontLeading,
            attrs,
        )
        return min(
            LIVE_MAX_HEIGHT,
            max(LIVE_MIN_HEIGHT, math.ceil(okvir.size.height) + LIVE_PAD * 2),
        )

    def _layout(self, text):
        width = self._width()
        height = self._height(text, width)
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            return
        v = screen.visibleFrame()
        # Kad je pilula sa vremenom takodje na dnu, okvir ide iznad nje.
        dno = LIVE_BOTTOM + (HEIGHT + 14 if self.avoid_pill else 0)
        x = v.origin.x + (v.size.width - width) / 2
        y = v.origin.y + dno
        self._panel.setFrame_display_(NSMakeRect(x, y, width, height), True)
        self._box.setFrame_(NSMakeRect(0, 0, width, height))
        self._label.setFrame_(
            NSMakeRect(LIVE_PAD, LIVE_PAD, width - LIVE_PAD * 2, height - LIVE_PAD * 2)
        )

    # ------------------------------------------------------------------

    def show(self, text=""):
        self._build()
        self.set_text(text)
        self._panel.orderFrontRegardless()
        self._visible = True

    def set_text(self, text):
        self._build()
        # Samo rep: dug diktat bi inace prerastao ekran, a gleda se ionako
        # poslednja recenica.
        clean = " ".join((text or "").split())[-LIVE_CHARS:]
        prikaz = clean or "Slušam…"
        if prikaz == self._text:
            return
        self._text = prikaz
        self._label.setStringValue_(prikaz)
        self._layout(prikaz)

    def hide(self):
        if self._panel is not None and self._visible:
            self._panel.orderOut_(None)
        self._visible = False
        self._text = ""
