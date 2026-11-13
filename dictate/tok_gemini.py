"""Gemini Transcribe Live: zvuk ide serveru DOK snimanje traje.

Prepis je gotov kad pustis taster. Izabran direktan upis privremeno menja
rep obicnog aktivnog polja; potvrda ga zakljucava.
"""

import time
from contextlib import nullcontext

from . import dijagnostika, geministt, insert, rezerva

LIVE_MREZNI_ROK = 20


class GeminiTok:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    def _recognize_gemini(self, pcm: bytes) -> str:
        return geministt.post_process(geministt.recognize(pcm, self.cfg), self.cfg)

    def _transcribe_live(self, recorder):
        """Salji zvuk Live API-ju DOK korisnik jos prica.

        Zasto ne kao OpenAI, tek posle Stop-a: izmereno na 64.7s zvuka, slanje
        posle Stop-a ostavlja **15.6s** cekanja, a slanje u toku **0.0s** —
        server stize u realnom vremenu, pa je prepis gotov u trenutku kad
        pustis taster. Broj prepoznatih celina je isti (11).

        Cena je ista: naplacuje se zvuk, a zvuk je isti. Mana je sto se komadi
        sa mikrofona citaju samo jednom — drugi pokusaj nema sta da posalje, pa
        neuspeo Live diktat se ne ponavlja sam. Zato postoji rezervni snimak
        (`rezerva.py`), iz koga se prepis ponavlja rucno.
        """
        session = self._dump.session() if self._dump else None
        if session is not None:
            self._debug_sessions[recorder.session] = session

        trace = (dijagnostika.LiveTrace(recorder.session)
                 if self.cfg.get("live_diagnostics", True) else None)
        self._live_trace = trace

        komadi = self._tracked(recorder)
        # `on_update` nosi ceo tekst za okvir. `on_interim` menja samo rep koji
        # je aplikacija sama upisala, `on_final` ga zakljucava. Sve ide kroz
        # isti tiket, pa izmena ne moze da pretekne raniji diktat.
        # Čuvanje radi i kada korisnik isključi crtanje okvira.
        prikaz = lambda tekst: self._live_preview(recorder, tekst)
        try:
            sirovo = geministt.recognize_live_stream(
            # Kratak mrezni rok: zvuk ide u realnom vremenu, pa ni jedno slanje
            # ni citanje ne sme da visi minutima. Pre je bio 180 s.
            komadi, self.cfg, timeout=LIVE_MREZNI_ROK,
            on_update=prikaz,
            on_final=(
                (lambda raw: self._live_part(recorder, raw))
                if getattr(recorder, "live_insert", False) else None
            ),
            on_interim=(
                (lambda raw: self._live_interim(recorder, raw))
                if getattr(recorder, "live_insert", False) else None
            ),
            on_diagnostic=trace.mark if trace is not None else None,
            )
        except Exception as exc:
            if trace is not None:
                trace.mark("error", type(exc).__name__)
            raise
        finally:
            if trace is not None:
                trace.mark("end")

        if recorder.cancelled:
            return ""
        self._settle_phase()
        text = geministt.post_process(sirovo, self.cfg)
        if session is not None:
            session.segment(session.next_index(), b"", text, kind="gemini_live")
            session.finish(b"", text)
        return text

    def _live_preview_on(self) -> bool:
        return bool(self.cfg.get("live_preview", True))

    def _live_preview(self, recorder, tekst: str):
        """Radna nit samo ostavlja tekst; okvir crta `_tick` sa glavne niti."""
        with getattr(self, "_session_lock", nullcontext()):
            if (recorder.cancelled or recorder.zaustavljen
                    or self._recorder is not recorder):
                return
            text = geministt.post_process(tekst, self.cfg).strip()
            if not text:
                return
            # Fajl i istorija se ažuriraju pre nego što UI dobije novi tekst.
            self._sacuvaj_prepis(recorder, text)
            self._live_text = text
            self._live_text_dirty = True
            self._live_last_update_at = time.monotonic()
            self._live_waiting = False

    def _live_part(self, recorder, raw):
        if recorder.cancelled:
            return
        text = geministt.post_process(raw, self.cfg).strip()
        if text:
            recorder.potvrdjeni_prepis = (
                (getattr(recorder, "potvrdjeni_prepis", "") + " " + text).strip()
            )
            self.upis.predaj_deo(recorder.ticket, text + " ", recorder.session)

    def _live_interim(self, recorder, raw):
        if recorder.cancelled:
            return
        text = geministt.post_process(raw, self.cfg).strip() if raw else ""
        self.upis.predaj_preview(recorder.ticket, text, recorder.session)

    def _apply_live_field_preview(self, text):
        applied = insert.preview_live(text)
        trace = getattr(self, "_live_trace", None)
        if trace is not None and text:
            if applied:
                trace.mark("field_ok", max(0, time.monotonic() - (trace.last_response or time.monotonic())))
            else:
                trace.mark("field_skip", insert.live_failure_reason())

    def _apply_live_field_final(self, text):
        insert.insert_live(text)
        trace = getattr(self, "_live_trace", None)
        if trace is not None:
            trace.mark("field_final", len(text))

    def _live_queue_wait(self, session, seconds):
        trace = getattr(self, "_live_trace", None)
        if trace is not None and trace.session == session:
            trace.mark("queue_wait", seconds)

    def _tick_live_panel(self):
        """Okvir sa prepisom uživo; sve se crta sa glavne niti."""
        # Zaustavljeno snimanje gasi okvir odmah, u sledecem otkucaju (50ms).
        # Reader jos radi i sme da posalje jos koju celinu — one idu u polje,
        # ali se vise ne crtaju.
        if self._live_off or (self._recorder is None and not self._starting):
            self._live_text_dirty = False
            # Tekst se ne briše ovde: Stop ga još mora prebaciti u polje.
            if self.live_panel.visible:
                self.live_panel.hide()
            return

        show_preview = self._live_preview_on()
        show_diagnostics = bool(self.cfg.get("live_diagnostics", True))
        google = (self.cfg.get("transcription_provider", "google") == "google"
                  and self._segmenting())
        if not ((show_preview or show_diagnostics) and (geministt.enabled(self.cfg) or google)):
            return
        recorder = self._recorder
        poslednji = getattr(self, "_live_last_update_at", time.monotonic())
        # Google salje tekst tek posle pauze (15 s i vise), pa kasnjenje nije znak kvara.
        if (recorder is not None and not google and not getattr(self, "_live_waiting", False)
                and time.monotonic() - poslednji > 4
                and time.monotonic() - getattr(recorder, "last_audio_at", 0) < 1
                and getattr(recorder, "level", 0) >= rezerva.PRAG_TISINE):
            self._live_waiting = True
            self._live_text_dirty = True
        # Kasnjenje se ne ispisuje: tacka u okviru postaje narandzasta i brze
        # pulsira, pa nema teksta koji treba procitati usred diktiranja.
        kasni = bool(getattr(self, "_live_waiting", False))
        if hasattr(self.live_panel, "set_delayed"):
            self.live_panel.set_delayed(kasni)
        status = ""
        trace = getattr(self, "_live_trace", None)
        if show_diagnostics and trace is not None:
            status = "\n".join(filter(None, (status, trace.snapshot())))
        # Okvir izlazi odmah, sa „Slušam…", a ne tek uz prvi tekst. Server
        # ponekad celoj sesiji ne pošalje nijedan međurezultat (izmereno: 2 od
        # 11 sesija, isti kod i isti snimak), pa bi prvi znak života inače bio
        # tek potvrđena celina na pauzi, u istom trenutku kad se tekst upiše.
        now = time.monotonic()
        diag_due = show_diagnostics and now - getattr(self, "_live_diag_drawn_at", 0) >= 0.5
        if self._live_text_dirty or diag_due or not self.live_panel.visible:
            self._live_text_dirty = False
            self._live_diag_drawn_at = now
            shown_text = self._live_text if show_preview else "Live diagnostics"
            self.live_panel.set_text(shown_text, status=status)
            if not self.live_panel.visible:
                self.live_panel.show(shown_text, status=status)
