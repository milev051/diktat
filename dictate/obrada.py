"""Sta se radi sa prepisom: lokalna pravila i AI obrada teksta.

AI obrada ceka kraj diktata (`_deferred`), da model vidi celinu.
"""

import threading
import traceback

from . import abbrev, config, insert, polish, webstt
from .pomoc import _label


class CekanjeObrade:
    """Stanje AI obrade: delovi diktata koji cekaju model i obrade u toku.

    Drzi ga samo ova klasa, kao sto `upis.RedUpisa` drzi svoje; ostatak
    aplikacije ga koristi kroz metode ispod. Delovi se drze PO SESIJI: nov
    diktat sme da pocne dok se prethodni obradjuje, pa bi u zajednickoj kanti
    dva diktata zavrsila u jednom pozivu i zalepila se spojena.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._delovi: dict[int, list[str]] = {}
        self._u_toku = 0

    def dodaj(self, sesija: int, tekst: str):
        with self._lock:
            self._delovi.setdefault(sesija, []).append(tekst)

    def sesije(self) -> list[int]:
        with self._lock:
            return list(self._delovi)

    def uzmi(self, sesija: int) -> str:
        """Ceo tekst sesije, i sesija vise ne ceka."""
        with self._lock:
            delovi = self._delovi.pop(sesija, [])
        return " ".join(d for d in delovi if d).strip()

    def pocni(self):
        with self._lock:
            self._u_toku += 1

    def zavrsi(self):
        with self._lock:
            self._u_toku = max(0, self._u_toku - 1)

    def radi(self) -> bool:
        """Ceka li se trenutno model (plava boja u traci menija)."""
        with self._lock:
            return self._u_toku > 0


class Obrada:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    def _write_ai_debug(self, session: int, trag: dict):
        """Upiši rezultate provajdera u log sesije ako je detaljan log uključen."""
        if not self._dump:
            return
        debug_session = self._debug_sessions.get(session)
        if debug_session is None:
            return
        debug_session.ai(
            trag.get("provider", "AI"),
            trag.get("google_text", ""),
            prompt=trag.get("prompt", ""),
            whisper_text=trag.get("whisper_text", ""),
            merged_text=trag.get("merged_text", ""),
            error=trag.get("error", ""),
            metadata=trag.get("metadata", ""),
        )

    def _apply_rules(self, text: str) -> str:
        """Nasa pravila nad jednim komadom teksta, bez prelamanja redova."""
        text = webstt.join_thousands(text)
        # Dve odluke su namerno nezavisne: moze se traziti samo mala slova,
        # samo uklanjanje znakova ili oba.
        text = self._apply_line_rules(text)
        text = self._skracenice(text)
        if self.cfg.get("ascii_diacritics", False):
            text = webstt.to_ascii(text)
        return text

    def _after_model(self, text: str) -> str:
        """Zavrsna podesavanja nad tekstom koji je model vec sredio.

        Lokalna prekidaca se primenjuju i posle modela, da ostanu nezavisna od
        toga da li je ukljuceno AI sredjivanje.
        """
        text = webstt.join_thousands(text)
        text = "\n".join(self._apply_line_rules(red) for red in text.split("\n"))
        text = self._skracenice(text)
        if self.cfg.get("ascii_diacritics", False):
            text = webstt.to_ascii(text)
        return text

    def _apply_line_rules(self, red: str) -> str:
        """Primeni lokalna pravila, ali sacuvaj oznaku bullet stavke."""
        oznaka = ""
        if red.startswith("- "):
            oznaka, red = "- ", red[2:]
        out = red
        if self.cfg.get("strip_punctuation", True):
            out = webstt.strip_punctuation(out)
        if self.cfg.get("lowercase", True):
            out = out.lower()
        else:
            # Pisani stil znaci i veliko slovo na pocetku recenice: model ga
            # ume propustiti, a granica ume da ostane i bez razmaka.
            out = webstt.capitalize_sentences(out)
        return oznaka + out

    def _skracenice(self, text: str) -> str:
        """Zamene koje korisnik sam definise; ista pravila kao na Androidu."""
        pravila = abbrev.parse(
            self.cfg.get("abbreviation_rules") or abbrev.default_text()
        ) if self.cfg.get("abbreviations", True) else []
        return abbrev.apply(
            text,
            pravila,
        )

    def _rules_over_paragraphs(self, text: str) -> str:
        """Ista pravila, ali PRELOM REDOVA prezivljava.

        `strip_punctuation` skuplja sve razmake u jedan, pa bi nad celim tekstom
        spojio i pasuse i tacke spiska u jedan red — a crtica, koja se tada
        nadje izmedju dva razmaka, i sama nestane. Zato red po red.
        """
        return "\n".join(self._apply_rules(red) for red in text.split("\n"))

    def _polish_today(self) -> int:
        import datetime
        if self.cfg.get("polish_count_day") != datetime.date.today().isoformat():
            return 0
        return int(self.cfg.get("polish_count", 0))

    def _count_polish(self, amount=1):
        """Brojač svih AI poziva po danu."""
        import datetime

        danas = datetime.date.today().isoformat()
        if self.cfg.get("polish_count_day") != danas:
            self.cfg["polish_count_day"] = danas
            self.cfg["polish_count"] = 0
        self.cfg["polish_count"] = int(self.cfg.get("polish_count", 0)) + amount
        config.save(self.cfg)

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
            tekst = self.ceka_obradu.uzmi(sesija)
            if not tekst:
                continue
            self.ceka_obradu.pocni()
            self.state.set(phase="polishing", message="")
            threading.Thread(
                target=self._do_polish, args=(sesija, tekst), daemon=True
            ).start()

    def _zavrsene(self, aktivna):
        """Sesije kojima je i zvuk i prepoznavanje gotovo."""
        return [
            s for s in self.ceka_obradu.sesije()
            if s != aktivna and self.upis.na_cekanju_sesije(s) == 0
        ]

    def _za_obradu(self, sesija: int, tekst: str):
        """Red za upis predaje deo diktata koji ceka AI obradu na kraju."""
        self.ceka_obradu.dodaj(sesija, tekst)

    def _posle_upisa(self):
        """Posle svakog prolaza reda: mozda je neki diktat ceo, i prikaz."""
        self._maybe_polish()
        self._settle_phase()

    def _do_polish(self, sesija: int, tekst: str):
        # Tekst je cekao kraj diktata pa je jos sirov: ako model ne doteruje,
        # pravila moraju sada da odrade svoje.
        doteran = (
            self._doteraj(tekst, session=sesija) if self._formal()
            else self._rules_over_paragraphs(tekst)
        )
        self.ceka_obradu.zavrsi()
        # Uz tacke ide nov red, a uz podelu na pasuse dva nova reda: sledeci
        # diktat tako ne moze da se zalepi za poslednji pasus.
        if self.cfg.get("polish_bullets", False):
            doteran = doteran.rstrip() + "\n"
        elif self._formal() and self.cfg.get("polish_paragraphs", True):
            doteran = doteran.rstrip() + "\n\n"
        else:
            doteran += " "
        debug_session = self._debug_sessions.pop(sesija, None)
        if debug_session is not None:
            debug_session.final(doteran)
        self.upis.zapamti(doteran)
        try:
            insert.insert(
                doteran,
                method=self.cfg.get("insert_method", "auto"),
                restore_clipboard=self.cfg.get("restore_clipboard", True),
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        self._settle_phase()

    def _doteraj(self, tekst: str, session=None) -> str:
        prompt = polish._uputstvo(self.cfg) if self._dump else ""
        try:
            doteran = polish.polish(tekst, self.cfg)
            self._count_polish()
            if polish.tidy_on(self.cfg):
                # Uz sredjivanje ostaju samo podesavanja koja se sa njim ne
                # sudaraju — tekst je modelu isao nedirnut, pa bi inace izostala.
                doteran = self._after_model(doteran)
            else:
                # Kad sredjivanje nije trazeno, model ga svejedno uradi cim
                # prepisuje recenice — skracivanje ih vraca pravopisno uredne.
                # Uputstvo to ne resava pouzdano, pa presudjuju nasa pravila.
                doteran = self._rules_over_paragraphs(doteran)
            self._write_ai_debug(session, {
                "provider": f"{polish.text_model_label(self.cfg)} tekstualna obrada",
                "google_text": tekst,
                "prompt": prompt,
                "merged_text": doteran,
            })
            return doteran
        except Exception as exc:  # noqa: BLE001
            # Nedoteran tekst je bolji nego nikakav — model je dodatak, ne uslov.
            self._write_ai_debug(session, {
                "provider": f"{polish.text_model_label(self.cfg)} tekstualna obrada",
                "google_text": tekst,
                "prompt": prompt,
                "error": str(exc),
            })
            print(f"[diktat] doterivanje nije uspelo: {exc}")
            return tekst

    def _deferred(self) -> bool:
        """Ceka li se kraj diktata zbog modela."""
        return self._formal()

    def _formal(self) -> bool:
        """Ceka li se ceo diktat zbog modela.

        Bez ijednog izabranog alata nema sta da se posalje, pa se tekst lepi
        odmah — inace bi diktat visio na praznom pozivu.
        """
        return polish.available(self.cfg) and bool(polish.tools(self.cfg))
