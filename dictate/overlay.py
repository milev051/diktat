"""Plutajuci HUD koji prikazuje stanje diktata na dnu ekrana.

Panel je `NSWindowStyleMaskNonactivatingPanel` i nikad ne preuzima fokus —
to je bitno jer se prepoznat tekst na kraju lepi u aplikaciju koja je bila
aktivna pre diktata.

Dve stvari koje nisu ocigledne:

  * Uglovi se zaobljavaju preko `setMaskImage_`, ne preko `cornerRadius`.
    `masksToBounds` sece samo slojeve iznad, a ne i zamucenu pozadinu koju
    crta window server — otud vidljiv providan pravougaonik na uglovima.

  * Merac koristi monospace font. Sa proporcionalnim, znaci ▁▂▃ i · nemaju
    istu sirinu pa ceo red poskakuje levo-desno kako se nivo menja.

Svi metodi se smeju zvati SAMO sa glavne niti (rumps Timer je na njoj).
"""

import AppKit
import Quartz
from Foundation import NSMakeRect, NSMakeSize

HEIGHT = 46
RADIUS = 14.0
PAD_X = 18.0
DOT = 9.0
DOT_GAP = 11.0
MIN_WIDTH = 150.0
MAX_WIDTH = 720.0

BOTTOM_MARGIN = 150      # za position="bottom"
EDGE_MARGIN = 12         # za position="top-right"

DOT_COLORS = {
    "recording": (1.00, 0.23, 0.19),    # crveno — snima
    "processing": (1.00, 0.78, 0.00),   # zuto — nesto se obradjuje
    "done": (0.20, 0.78, 0.35),
    "error": (1.00, 0.45, 0.05),
}
DOT_COLORS["thinking"] = DOT_COLORS["processing"]


def _cgcolor(rgb):
    return Quartz.CGColorCreateGenericRGB(rgb[0], rgb[1], rgb[2], 1.0)


def _rounded_mask(size, radius=RADIUS):
    """Maska za NSVisualEffectView — jedini nacin da se zamucena pozadina zaobli."""
    image = AppKit.NSImage.alloc().initWithSize_(size)
    image.lockFocus()
    AppKit.NSColor.blackColor().set()
    AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(0, 0, size.width, size.height), radius, radius
    ).fill()
    image.unlockFocus()
    image.setCapInsets_(AppKit.NSEdgeInsetsMake(radius, radius, radius, radius))
    image.setResizingMode_(AppKit.NSImageResizingModeStretch)
    return image


class Overlay:
    def __init__(self, position="bottom"):
        self.position = position if position in ("bottom", "top-right") else "bottom"
        self._panel = None
        self._blur = None
        self._label = None
        self._dot = None
        self._visible = False
        self._mono_font = AppKit.NSFont.monospacedSystemFontOfSize_weight_(
            14, AppKit.NSFontWeightMedium
        )
        self._text_font = AppKit.NSFont.systemFontOfSize_weight_(
            16, AppKit.NSFontWeightMedium
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

        blur = AppKit.NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, MIN_WIDTH, HEIGHT)
        )
        blur.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        blur.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        blur.setState_(AppKit.NSVisualEffectStateActive)
        blur.setMaskImage_(_rounded_mask(NSMakeSize(MIN_WIDTH, HEIGHT)))
        panel.setContentView_(blur)

        dot = AppKit.NSView.alloc().initWithFrame_(
            NSMakeRect(PAD_X, (HEIGHT - DOT) / 2, DOT, DOT)
        )
        dot.setWantsLayer_(True)
        dot.layer().setCornerRadius_(DOT / 2)
        dot.layer().setBackgroundColor_(_cgcolor(DOT_COLORS["recording"]))
        blur.addSubview_(dot)

        label = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(PAD_X + DOT + DOT_GAP, 0, 10, HEIGHT)
        )
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(self._mono_font)
        label.setTextColor_(AppKit.NSColor.labelColor())
        label.setAlignment_(AppKit.NSTextAlignmentLeft)
        label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingHead)
        label.setUsesSingleLineMode_(True)
        label.setMaximumNumberOfLines_(1)
        label.setStringValue_("")
        blur.addSubview_(label)

        self._panel = panel
        self._blur = blur
        self._label = label
        self._dot = dot

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

    def _layout(self, text, mono):
        """Sirina se prilagodjava tekstu, a tackica i tekst se drze kao jedna
        celina centrirana u panelu — inace, kad MIN_WIDTH rastegne panel,
        levo poravnat tekst ostavi sav visak sa desne strane."""
        font = self._mono_font if mono else self._text_font
        if self._label.font() is not font:
            self._label.setFont_(font)

        text_w = self._measure(text, font)
        width = min(MAX_WIDTH, max(MIN_WIDTH, PAD_X * 2 + DOT + DOT_GAP + text_w))
        label_w = min(text_w, width - PAD_X * 2 - DOT - DOT_GAP)
        group_w = DOT + DOT_GAP + label_w
        group_x = (width - group_w) / 2

        # Vertikalno: tackica ide na sredinu visine cifara (cap height), ne na
        # geometrijsku sredinu reda — tako oko vidi da su poravnate.
        line_h = font.ascender() - font.descender()
        label_y = (HEIGHT - line_h) / 2
        baseline = label_y - font.descender()
        dot_y = baseline + font.capHeight() / 2 - DOT / 2

        self._label.setFrame_(
            NSMakeRect(group_x + DOT + DOT_GAP, label_y, label_w, line_h)
        )
        self._dot.setFrame_(NSMakeRect(group_x, dot_y, DOT, DOT))

        origin = self._origin(width)
        if origin is None:
            return
        x, y = origin
        current = self._panel.frame()
        if abs(current.size.width - width) > 0.5 or abs(current.origin.x - x) > 0.5:
            self._panel.setFrame_display_(NSMakeRect(x, y, width, HEIGHT), True)
            self._blur.setFrame_(NSMakeRect(0, 0, width, HEIGHT))
            self._blur.setMaskImage_(_rounded_mask(NSMakeSize(width, HEIGHT)))

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

    def set_state(self, color):
        if self._dot is None:
            return
        self._dot.layer().setBackgroundColor_(
            _cgcolor(DOT_COLORS.get(color, DOT_COLORS["recording"]))
        )

    def hide(self):
        if self._panel is not None and self._visible:
            self._panel.orderOut_(None)
        self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible
