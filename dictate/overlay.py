"""Plutajuci HUD koji prikazuje tekst uzivo dok pricas.

Panel je `NSWindowStyleMaskNonactivatingPanel` i nikad ne preuzima fokus —
to je bitno jer se prepoznat tekst na kraju lepi u aplikaciju koja je bila
aktivna pre diktata.

Svi metodi se smeju zvati SAMO sa glavne niti (rumps Timer je na njoj).
"""

import AppKit
import Quartz
from Foundation import NSMakeRect

WIDTH = 760
HEIGHT = 92
BOTTOM_MARGIN = 140

# Eksplicitni CGColor-i; NSColor.CGColor() preko PyObjC-a baca ObjCPointerWarning.
DOT_COLORS = {
    "recording": (1.00, 0.23, 0.19),
    "thinking": (1.00, 0.80, 0.00),
    "done": (0.20, 0.78, 0.35),
    "error": (1.00, 0.58, 0.00),
}


def _cgcolor(rgb):
    return Quartz.CGColorCreateGenericRGB(rgb[0], rgb[1], rgb[2], 1.0)


class Overlay:
    def __init__(self):
        self._panel = None
        self._label = None
        self._dot = None
        self._visible = False

    # ------------------------------------------------------------------

    def _build(self):
        if self._panel is not None:
            return

        style = (
            AppKit.NSWindowStyleMaskBorderless
            | AppKit.NSWindowStyleMaskNonactivatingPanel
        )
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), style, AppKit.NSBackingStoreBuffered, False
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
            NSMakeRect(0, 0, WIDTH, HEIGHT)
        )
        blur.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        blur.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        blur.setState_(AppKit.NSVisualEffectStateActive)
        blur.setWantsLayer_(True)
        blur.layer().setCornerRadius_(20.0)
        blur.layer().setMasksToBounds_(True)
        panel.setContentView_(blur)

        dot = AppKit.NSView.alloc().initWithFrame_(NSMakeRect(26, HEIGHT / 2 - 6, 12, 12))
        dot.setWantsLayer_(True)
        dot.layer().setCornerRadius_(6.0)
        dot.layer().setBackgroundColor_(_cgcolor(DOT_COLORS["recording"]))
        blur.addSubview_(dot)

        label = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(54, HEIGHT / 2 - 17, WIDTH - 80, 34)
        )
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(21, AppKit.NSFontWeightMedium)
        )
        label.setTextColor_(AppKit.NSColor.labelColor())
        label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingHead)
        label.setUsesSingleLineMode_(True)
        label.setMaximumNumberOfLines_(1)
        label.setStringValue_("")
        blur.addSubview_(label)

        self._panel = panel
        self._label = label
        self._dot = dot
        self._reposition()

    def _reposition(self):
        screen = AppKit.NSScreen.mainScreen()
        if screen is None:
            return
        frame = screen.visibleFrame()
        x = frame.origin.x + (frame.size.width - WIDTH) / 2
        y = frame.origin.y + BOTTOM_MARGIN
        self._panel.setFrameOrigin_((x, y))

    # ------------------------------------------------------------------

    def show(self, text=""):
        self._build()
        self._reposition()
        self._label.setStringValue_(text)
        self._panel.orderFrontRegardless()
        self._visible = True

    def set_text(self, text: str):
        if self._label is not None and self._visible:
            self._label.setStringValue_(text)

    def set_state(self, color):
        """color: 'recording' (crveno) | 'thinking' (zuto) | 'done' (zeleno)."""
        if self._dot is None:
            return
        rgb = DOT_COLORS.get(color, DOT_COLORS["recording"])
        self._dot.layer().setBackgroundColor_(_cgcolor(rgb))

    def hide(self):
        if self._panel is not None and self._visible:
            self._panel.orderOut_(None)
        self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible
