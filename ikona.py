"""Crta ikonu Diktata: mikrofon na tamnoj pozadini.

Poziva je `make_app.sh`; crta se kroz AppKit, koji je vec u .venv-u zbog
rumps-a, pa aplikacija ne dobija nijednu novu zavisnost samo zbog ikone.

    .venv/bin/python ikona.py izlaz.png
"""
import sys
from AppKit import (
    NSBitmapImageRep, NSGraphicsContext, NSColor, NSBezierPath,
    NSCalibratedRGBColorSpace, NSPNGFileType, NSGradient,
)

S = 1024.0


def boja(r, g, b):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r / 255.0, g / 255.0, b / 255.0, 1.0)


rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, int(S), int(S), 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0
)
ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.setCurrentContext_(ctx)

# Pozadina: zaobljen kvadrat sa blagim prelazom, kao ostale macOS ikone.
pozadina = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
    ((0, 0), (S, S)), 224, 224
)
NSGradient.alloc().initWithStartingColor_endingColor_(
    boja(20, 26, 41), boja(59, 74, 107)
).drawInBezierPath_angle_(pozadina, 90.0)

NSColor.whiteColor().set()

# Glava mikrofona.
NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
    ((382, 430), (260, 390)), 130, 130
).fill()

# Luk ispod glave.
luk = NSBezierPath.bezierPath()
luk.setLineWidth_(52)
luk.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
    (512, 496), 236, 180, 0, False
)
luk.stroke()

# Drska i postolje.
NSBezierPath.bezierPathWithRect_(((484, 168), (56, 110))).fill()
NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
    ((352, 150), (320, 58)), 29, 29
).fill()

NSGraphicsContext.restoreGraphicsState()
rep.representationUsingType_properties_(NSPNGFileType, None).writeToFile_atomically_(
    sys.argv[1], True
)
print(sys.argv[1])
