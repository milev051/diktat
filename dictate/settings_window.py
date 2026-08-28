"""Jednostavan macOS prozor sa istim grupama podesavanja kao Android."""

from pathlib import Path
import subprocess

import AppKit
from Foundation import NSMakeRect, NSMakeSize


# Naziv izvora transkripcije stoji na JEDNOM mestu: iz njega se pravi spisak u
# prozoru, iz njega se cita nazad izabrana stavka. Dva spiska bi se razisla cim
# se doda treci izvor — bas to se i desilo kad su dosli Gemini modeli.
PROVIDER_TITLES = {
    "google": "Google Speech-to-Text",
    "openai": "OpenAI GPT Transcribe",
    "gemini_live": "Gemini 3.5 Transcribe Live",
}


def provider_from_title(title: str) -> str:
    """Izabrana stavka -> kljuc podesavanja; nepoznato pada na Google."""
    for ime, naslov in PROVIDER_TITLES.items():
        if naslov == title:
            return ime
    return "google"


class SettingsWindow:
    WIDTH = 560.0
    HEIGHT = 780.0
    DOCUMENT_HEIGHT = 1900.0

    def __init__(self, app):
        self.app = app
        self.window = None
        self.document = None
        self.controls = {}
        self.provider_controls = {}

    def show(self):
        if self.window is not None:
            self.refresh()
            self.window.makeKeyAndOrderFront_(None)
            AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            return

        masks = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
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
        self.window.setMinSize_(NSMakeSize(480, 600))

        scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(False)
        scroll.setBorderType_(AppKit.NSNoBorder)
        self.document = AppKit.NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, self.WIDTH, self.DOCUMENT_HEIGHT)
        )
        scroll.setDocumentView_(self.document)
        self.window.setContentView_(scroll)

        y = self.DOCUMENT_HEIGHT - 28.0

        def add(view, height):
            nonlocal y
            y -= height
            view.setFrame_(NSMakeRect(24, y, self.WIDTH - 48, height))
            self.document.addSubview_(view)
            return view

        def label(text, height=24, size=13, bold=False, alpha=1.0):
            field = AppKit.NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
            field.setStringValue_(text)
            field.setEditable_(False)
            field.setSelectable_(False)
            field.setBordered_(False)
            field.setDrawsBackground_(False)
            font = (
                AppKit.NSFont.boldSystemFontOfSize_(size)
                if bold else AppKit.NSFont.systemFontOfSize_(size)
            )
            field.setFont_(font)
            field.setTextColor_(AppKit.NSColor.labelColor())
            field.setAlphaValue_(alpha)
            return add(field, height)

        def section(title, description=""):
            label(title, 28, 17, bold=True)
            if description:
                label(description, 38, 12, alpha=0.72)

        def button(title, action, height=30, identifier=None):
            item = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
            item.setTitle_(title)
            item.setBezelStyle_(AppKit.NSBezelStyleRounded)
            item.setTarget_(self.app)
            item.setAction_("settingsButton:")
            item.setIdentifier_(identifier or action)
            return add(item, height)

        def checkbox(title, key, default=None, provider=None):
            item = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
            item.setButtonType_(AppKit.NSSwitchButton)
            item.setTitle_(title)
            item.setTarget_(self.app)
            item.setAction_("settingsCheckbox:")
            item.setIdentifier_(key)
            value = self.app.cfg.get(key, default)
            item.setState_(
                AppKit.NSControlStateValueOn if bool(value)
                else AppKit.NSControlStateValueOff
            )
            control = add(item, 30)
            self.controls[key] = control
            if provider:
                imena = (provider,) if isinstance(provider, str) else tuple(provider)
                self.provider_controls.setdefault(imena, []).append(control)
            return control

        def popup(title, key, values, selected):
            label(title, 22, 12, alpha=0.72)
            item = AppKit.NSPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
            item.addItemsWithTitles_(values)
            if selected in values:
                item.selectItemWithTitle_(selected)
            item.setTarget_(self.app)
            item.setAction_("settingsPopup:")
            item.setIdentifier_(key)
            control = add(item, 32)
            self.controls[key] = control
            return control

        def field(title, key, secure=False):
            label(title, 22, 12, alpha=0.72)
            cls = AppKit.NSSecureTextField if secure else AppKit.NSTextField
            item = cls.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
            item.setStringValue_(str(self.app.cfg.get(key, "")))
            item.setIdentifier_(key)
            item.setDelegate_(self.app)
            control = add(item, 32)
            self.controls[key] = control
            return control

        label("Diktat", 38, 24, bold=True)
        label(
            "Podešavanja su grupisana isto kao u mobilnoj aplikaciji. Promene se čuvaju u lokalnom config.json fajlu.",
            40, 12, alpha=0.72,
        )

        section("Istorija diktata", "Poslednjih 5 uspešnih rezultata dostupno je iz menija Istorija.")
        button("Obriši istoriju", "clear_history")

        section("Sačuvani audio", "Ako transkripcija ne uspe, audio se čuva lokalno za ponovni pokušaj.")
        button("Otvori folder sa sačuvanim snimcima", "open_pending")

        section("Dozvole", "Za unos teksta u aktivnu aplikaciju potrebna je Accessibility dozvola.")
        button("Otvori Accessibility podešavanja", "accessibility")
        button("Otvori podešavanja mikrofona", "microphone")

        section(
            "Glasovni unos",
            "Servis koji pretvara govor u tekst. Gemini Transcribe koristi isti "
            "ključ kao AI obrada i prima duže snimke od besplatnog Google-a.",
        )
        popup(
            "Provider transkripcije",
            "transcription_provider",
            list(PROVIDER_TITLES.values()),
            PROVIDER_TITLES.get(
                self.app.cfg.get("transcription_provider", "google"),
                PROVIDER_TITLES["google"],
            ),
        )
        checkbox(
            "Neprekidno snimanje (seče na pauzama)", "continuous", True,
            provider=("google", "gemini_live"),
        )
        checkbox("OpenAI dugi diktat (do 60 min)", "openai_long_recording", True, provider="openai")
        label("OpenAI izlazno pismo: Latinica (fiksno)", 28, 12, alpha=0.72)

        section("Ispravka teksta pomoću AI", "Odvojeno od transkripcije: model sređuje već dobijeni tekst.")
        popup(
            "Model za manipulaciju teksta",
            "text_model",
            ["Gemini", "Groq GPT-OSS 120B"],
            "Groq GPT-OSS 120B" if self.app.cfg.get("text_model") == "groq" else "Gemini",
        )
        checkbox("Sredi tekst (tačke i velika slova)", "text_style_written", False)
        checkbox("Podeli na pasuse", "polish_paragraphs", True)
        checkbox("Sažmi u tačke", "polish_bullets", False)
        checkbox("Izbaci ponavljanja", "polish_dedupe", False)
        label("Jezik izlaza: prazno znači bez prevoda", 28, 12, alpha=0.72)
        field("Jezik izlaza", "output_language")

        section("API ključevi", "Svaki servis ima posebno polje; ključevi ostaju lokalno sačuvani.")
        field("Gemini API ključ", "polish_api_key", secure=True)
        field("Groq API ključ", "groq_api_key", secure=True)
        field("OpenAI API ključ", "openai_api_key", secure=True)
        button("Proveri sve API ključeve", "check_api")

        section("Tekst", "Lokalna pravila koja rade i bez AI modela.")
        checkbox("Sva slova mala", "lowercase", True)
        checkbox("Ukloni interpunkciju (brojevi ostaju)", "strip_punctuation", True)
        checkbox("Bez kvačica", "ascii_diacritics", False)
        checkbox("Skraćuj česte fraze", "abbreviations", True)

        section("Potrošnja podataka", "Ukupno snimljeno vreme čuva se lokalno i koristi se u metrici.")
        label(
            f"Ukupno snimljeno: {self.app._recorded_seconds():.0f} s",
            28, 13,
        )

        section("Procena koristi — 10 dana", "Prati diktate, karaktere, vreme snimanja i modele.")
        button("Prikaži izveštaj", "utility_report")
        button("Pokreni novu procenu (briše staru)", "utility_start")

        self.refresh()
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def refresh(self):
        if self.window is None:
            return
        provider = self.app.cfg.get("transcription_provider", "google")
        for imena, views in self.provider_controls.items():
            for view in views:
                view.setHidden_(provider not in imena)
        for key, view in self.controls.items():
            if key == "transcription_provider" or key == "text_model":
                continue
            if key == "text_style_written":
                value = self.app.cfg.get("text_style") == "written"
            else:
                value = self.app.cfg.get(key, False)
            if hasattr(view, "setState_"):
                view.setState_(
                    AppKit.NSControlStateValueOn if bool(value)
                    else AppKit.NSControlStateValueOff
                )

    def save_fields(self):
        for key in ("polish_api_key", "groq_api_key", "openai_api_key", "output_language"):
            field = self.controls.get(key)
            if field is not None:
                self.app.cfg[key] = field.stringValue().strip()

    def open_pending(self):
        path = Path(self.app.cfg.get("pending_dir", "~/Diktat-neuspeli")).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["open", str(path)])
