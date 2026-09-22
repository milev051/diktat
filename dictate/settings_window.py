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
from Foundation import NSAttributedString, NSMakeRect, NSMakeSize

from . import audio, azuriranje, config, hotkey, rezerva


# Naziv izvora transkripcije stoji na JEDNOM mestu: iz njega se pravi spisak u
# prozoru, iz njega se cita nazad izabrana stavka. Dva spiska bi se razisla cim
# se doda treci izvor — bas to se i desilo kad su dosli Gemini modeli.
PROVIDER_TITLES = {
    "google": "Google Speech-to-Text",
    "openai": "OpenAI GPT Transcribe",
    "gemini_live": "Gemini 3.5 Transcribe Live",
}

MIKROFON_PODRAZUMEVANI = "Sistemski podrazumevani"

COLUMN = 330.0        # sirina jedne od tri kolone
KOLONA_RAZMAK = 44.0  # razmak izmedju kolona
IVICA = 32.0          # margina prozora levo, desno i dole
ZAGLAVLJE = 104.0     # visina reda sa dugmadima i ukupnim vremenom
GAP = 8.0             # razmak izmedju dve kontrole
SECTION_GAP = 26.0    # razmak PRE naslova grupe
SACUVANI_REDOVA = 3   # koliko sacuvanih snimaka se nudi za prepis
NASLOV_MENIJA = "Diktat"  # po njemu se prepoznaje nas glavni meni
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


class _Prozor(AppKit.NSWindow):
    """Prozor koji sam zna za ⌘W i za ⌘C/⌘V/⌘X/⌘A/⌘Z u poljima.

    Glavni meni (`_glavni_meni`) je bio dovoljan kad se prozor pokrene sam, ali
    ne i u aplikaciji: tamo ⌘W nije zatvarao prozor (22.09.2026). Prozor zato
    precice hvata i sam, pre menija, pa ne zavisi od toga ciji je meni u
    traci ni da li je stigao da se postavi.
    """

    PRECICE = {"w": "performClose:", "c": "copy:", "v": "paste:", "x": "cut:",
               "a": "selectAll:", "z": "undo:"}

    def performKeyEquivalent_(self, event):  # noqa: N802 - ime trazi AppKit
        maska = event.modifierFlags() & AppKit.NSEventModifierFlagDeviceIndependentFlagsMask
        taster = (event.charactersIgnoringModifiers() or "").lower()
        if maska == AppKit.NSEventModifierFlagCommand and taster in self.PRECICE:
            akcija = self.PRECICE[taster]
            if akcija == "performClose:":
                self.performClose_(None)
                return True
            if AppKit.NSApplication.sharedApplication().sendAction_to_from_(akcija, None, self):
                return True
        return objc.super(_Prozor, self).performKeyEquivalent_(event)


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
    """Sva podesavanja na jednom ekranu, u tri kolone, bez kartica.

    Prozor nema promenu velicine: sirina je zbir kolona, visina najvisa
    kolona. Kad se grupa skloni ili pojavi, prozor se sam skrati ili produzi
    (`_rasporedi`), a gornja ivica ostaje na mestu.
    """

    WIDTH = 3 * COLUMN + 2 * KOLONA_RAZMAK + 2 * IVICA

    def __init__(self, app):
        self.app = app
        self.window = None
        self.pages = []
        self.document = None
        self.delegate = None
        self.controls = {}
        self.history_buttons = []
        self.microphone_popup = None
        self.stop_button = None
        self.quit_button = None
        self.recorded_label = None
        self.update_header = None
        self.saved_rows = []
        self._sacuvani = []
        self.prepis_label = None
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
        _glavni_meni(nsapp)
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
        self.window.setTitle_("Diktat — Podešavanja")
        self.window.setReleasedWhenClosed_(False)
        # Svoje mesto u Mission Control-u: bez ovoga se prozor menu-bar
        # aplikacije ponasa kao pomocni panel iznad tudjeg prozora.
        self.window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorManaged)
        self.delegate = _WindowDelegate.alloc().initWithOwner_(self)
        self.window.setDelegate_(self.delegate)

        # Skrol postoji samo za ekran nizi od sadrzaja; inace se ne vidi.
        scroll = AppKit.NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, self.WIDTH, 600))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setBorderType_(AppKit.NSNoBorder)
        scroll.setDrawsBackground_(False)
        self.document = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, self.WIDTH, 600))
        scroll.setDocumentView_(self.document)
        self.window.setContentView_(scroll)

        # Zaglavlje: tri dugmeta na sredini, ispod njih ukupno snimljeno.
        # „Zaustavi snimanje" stoji sivo dok nema sta da zaustavi, da dugmad
        # ne poskakuju. Trenutna verzija je u natpisu dugmeta za azuriranje.
        self.stop_button = self._plain_button("Zaustavi snimanje", "stop_recording")
        self.stop_button.setEnabled_(False)
        self.update_header = self._plain_button("Proveri ažuriranje", "update")
        self.quit_button = self._plain_button("Zatvori Diktat", "quit")
        sirine = (190.0, 250.0, 190.0)
        razmak = 12.0
        x = (self.WIDTH - sum(sirine) - 2 * razmak) / 2
        for dugme, sirina in zip(
            (self.stop_button, self.update_header, self.quit_button), sirine
        ):
            dugme.setFrame_(NSMakeRect(x, 24, sirina, 30))
            self.document.addSubview_(dugme)
            x += sirina + razmak

        self.recorded_label = self._plain_label("", 12, alpha=0.6)
        self.recorded_label.setAlignment_(AppKit.NSTextAlignmentCenter)
        self.recorded_label.setFrame_(NSMakeRect(0, 64, self.WIDTH, 18))
        self.document.addSubview_(self.recorded_label)

        self.pages = [
            self._kolona_snimanje(),
            self._kolona_tekst(),
            self._kolona_kljucevi(),
        ]
        for broj, page in enumerate(self.pages):
            page.column.setFrameOrigin_(
                AppKit.NSMakePoint(IVICA + broj * (COLUMN + KOLONA_RAZMAK), ZAGLAVLJE)
            )
            self.document.addSubview_(page.column)
        # Tanka uspravna linija izmedju kolona.
        for broj in (1, 2):
            linija = AppKit.NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 10))
            linija.setBoxType_(AppKit.NSBoxSeparator)
            x = IVICA + broj * (COLUMN + KOLONA_RAZMAK) - KOLONA_RAZMAK / 2
            linija.setFrame_(NSMakeRect(x, ZAGLAVLJE, 1, 10))
            self.document.addSubview_(linija)
            self.dividers.append(linija)

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

    def _ai_ukljucen(self) -> bool:
        return config.ai_obrada(self.app.cfg)

    def _lokalna_ukljucena(self) -> bool:
        """Sva cetiri ugasena znaci „pravilno", tj. grupa je iskljucena."""
        return not config.pravilno(self.app.cfg)

    def _dozvole_ok(self) -> bool:
        return self._accessibility_ok and self._mikrofon_ok

    # ----------------------------------------------------------- kartice

    def _kolona_snimanje(self) -> _Page:
        """Od glasa do prepisa: mikrofon, servis, provera, dozvole."""
        page = _Page()

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

        self._section(page, "Prepoznavanje govora")
        self._popup(
            page, "Servis", "transcription_provider",
            list(PROVIDER_TITLES.values()),
            PROVIDER_TITLES.get(self._provider(), PROVIDER_TITLES["google"]),
        )
        # Stoji uz servis, ne uz taster: da li se sece na pauzama zavisi od
        # toga ko prepoznaje, a uz OpenAI ne postoji.
        self._checkbox(
            page, "Neprekidno snimanje (seče na pauzama)", "continuous", True,
            vidljivo=self._samo_za("google", "gemini_live"),
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

        # Dozvola koja postoji nema šta da se traži; grupa se vidi samo kad
        # nešto zaista fali.
        self._section(page, "Dozvole", vidljivo=lambda: not self._dozvole_ok(),
                      sakrij=True)
        self._hint(page, "Bez Accessibility dozvole tekst završava u clipboard-u "
                         "umesto u aktivnom polju.",
                   vidljivo=lambda: not self._accessibility_ok, sakrij=True)
        self._button(page, "Otvori Accessibility", "accessibility",
                     vidljivo=lambda: not self._accessibility_ok, sakrij=True)
        self._hint(page, "Snimanje je zabranjeno u sistemskim podešavanjima.",
                   vidljivo=lambda: not self._mikrofon_ok, sakrij=True)
        self._button(page, "Otvori podešavanja mikrofona", "microphone",
                     vidljivo=lambda: not self._mikrofon_ok, sakrij=True)
        return page

    def _kolona_tekst(self) -> _Page:
        """Sta se radi sa prepisom: AI obrada pa lokalna pravila."""
        page = _Page()
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
                   vidljivo=lambda: not self._lokalna_ukljucena(), sakrij=True)

        return page

    def _kolona_kljucevi(self) -> _Page:
        page = _Page()
        self._section(page, "API ključevi", "Ostaju lokalno u config.json.")
        self._field(page, "Gemini (transkripcija Live i obrada teksta)", "polish_api_key",
                    secure=True)
        self._field(page, "Groq (obrada teksta)", "groq_api_key",
                    secure=True)
        self._field(page, "OpenAI (GPT transkripcija)", "openai_api_key", secure=True)
        self._button(page, "Proveri sve ključeve", "check_api")

        self._section(page, "Poslednjih pet diktata", "Klikni na red da kopiraš tekst.")
        for index in range(5):
            self.history_buttons.append(
                self._button(
                    page, "", f"copy_history_{index}", full_width=True,
                    vidljivo=lambda i=index: i < self._history_len, sakrij=True,
                )
            )
        self._hint(page, "Još ništa nije izdiktirano.",
                   vidljivo=lambda: self._history_len == 0, sakrij=True)

        self._section(page, "Sačuvani snimci",
                      f"Diktat koji nije prepisan čuva se {rezerva.ROK_SATI} h.")
        self._checkbox(page, "Čuvaj snimak dok se ne prepiše", "rezervni_snimak", True)
        for index in range(SACUVANI_REDOVA):
            red = _RedSnimka.napravi(self, index)
            self.saved_rows.append(red)
            page.place(red.view, 28, gap=4.0,
                       vidljivo=lambda i=index: i < len(self._sacuvani), sakrij=True)
        self._hint(page, "Nema sačuvanih snimaka.",
                   vidljivo=lambda: not self._sacuvani, sakrij=True)
        # Dva reda: ishod prepisa ume da bude duzi od kolone.
        self.prepis_label = self._plain_label("", 12, alpha=0.6)
        self._text_height(self.prepis_label, COLUMN, 17.0)
        page.place(self.prepis_label, 34, vidljivo=lambda: bool(self.app.prepis_status),
                   sakrij=True)
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
            return page.place(item, 26, gap=6.0, vidljivo=vidljivo, sakrij=sakrij)
        item.sizeToFit()
        sirina = min(COLUMN, max(item.frame().size.width + 28, 150.0))
        return page.place_left(item, 30, sirina, gap=6.0, vidljivo=vidljivo,
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

        history = self.app.upis.istorija()
        self._history_len = len(history)
        for index, view in enumerate(self.history_buttons):
            if index < len(history):
                short = " ".join(history[index].split())
                view.setTitle_(f"  {index + 1}. {short[:46]}")

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

        self._sacuvani = self.app.sacuvani_snimci()[:SACUVANI_REDOVA]
        for index, red in enumerate(self.saved_rows):
            if index < len(self._sacuvani):
                red.oznaka.setStringValue_(self._sacuvani[index].naslov())
            red.prepisi.setEnabled_(not self.app._prepis_radi)
        if self.prepis_label is not None:
            self.prepis_label.setStringValue_(self.app.prepis_status)

        self._refresh_update()

        self._rasporedi()

    def _refresh_update(self):
        if self.update_header is None:
            return
        dostupno = self.app.azur_dugme_stanje()[1]
        # Obican `setTitle_` brise zelen natpis, pa se boja nanosi posle njega.
        self.update_header.setTitle_(self.app.azur_dugme_stanje()[0])
        _zeleno(self.update_header, dostupno)
        self.update_header.setToolTip_(self.app._azur_status or None)

    def refresh_recording(self):
        if self.stop_button is not None:
            active = self.app._recorder is not None or bool(self.app._starting)
            if bool(self.stop_button.isEnabled()) != active:
                self.stop_button.setEnabled_(active)


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


def _glavni_meni(nsapp):
    """Prečice koje svaki prozor ima: ⌘W zatvara, ⌘C/⌘V/⌘X/⌘A/⌘Z u poljima.

    Menu-bar aplikacija nema glavni meni, a macOS prečice ne vezuje za prozor
    nego za stavke tog menija. Bez njega ⌘W ne zatvara prozor, a ⌘V ne lepi
    ključ u polje. Stavke nemaju cilj (`target`), pa idu prvom koji ume da ih
    izvrši: polju u fokusu ili samom prozoru.
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

    podmeni("Diktat", [("Zatvori prozor", "performClose:", "w")])
    podmeni("Izmeni", [
        ("Poništi", "undo:", "z"),
        ("Iseci", "cut:", "x"),
        ("Kopiraj", "copy:", "c"),
        ("Nalepi", "paste:", "v"),
        ("Izaberi sve", "selectAll:", "a"),
    ])
    nsapp.setMainMenu_(glavni)


def _omoguci(view, ukljuceno: bool, alpha: float):
    """Opcija bez smisla ostaje vidljiva, ali zatamnjena i neaktivna."""
    view.setHidden_(False)
    natpis = isinstance(view, AppKit.NSTextField) and not view.isEditable()
    if isinstance(view, AppKit.NSControl) and not natpis:
        view.setEnabled_(ukljuceno)
    view.setAlphaValue_(alpha if ukljuceno else alpha * 0.4)


class _RedSnimka:
    """Red u listi sacuvanih snimaka: vreme i trajanje, Prepiši, Obriši."""

    def __init__(self, view, oznaka, prepisi, obrisi):
        self.view = view
        self.oznaka = oznaka
        self.prepisi = prepisi
        self.obrisi = obrisi

    @classmethod
    def napravi(cls, prozor, index):
        view = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, COLUMN, 28))
        oznaka = prozor._plain_label("", 13)
        oznaka.setFrame_(NSMakeRect(0, 5, COLUMN - 190, 18))
        prepisi = prozor._plain_button("Prepiši", f"prepisi_{index}")
        prepisi.setFrame_(NSMakeRect(COLUMN - 186, 0, 96, 28))
        obrisi = prozor._plain_button("Obriši", f"obrisi_{index}")
        obrisi.setFrame_(NSMakeRect(COLUMN - 88, 0, 88, 28))
        for deo in (oznaka, prepisi, obrisi):
            view.addSubview_(deo)
        return cls(view, oznaka, prepisi, obrisi)
