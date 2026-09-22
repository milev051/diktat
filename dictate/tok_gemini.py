"""Gemini Transcribe Live: zvuk ide serveru DOK snimanje traje.

Prepis je gotov kad pustis taster. Medjurezultat ide samo u okvir na ekranu,
u polje ide samo potvrdjena celina.
"""

from . import geministt, rezerva

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

        komadi = self._tracked(recorder)
        # `on_update` nosi ceo tekst do tog trenutka (potvrđeno + međurezultat) i
        # ide SAMO u okvir na ekranu. U polje se kuca tek potvrđena celina
        # (`on_final`): međurezultat model sme da promeni, pa bi kasnija izmena
        # obrisala ručnu ispravku.
        prikaz = (
            (lambda tekst: self._live_preview(recorder, tekst))
            if self._live_preview_on() else None
        )
        sirovo = geministt.recognize_live_stream(
            # Kratak mrezni rok: zvuk ide u realnom vremenu, pa ni jedno slanje
            # ni citanje ne sme da visi minutima. Pre je bio 180 s.
            komadi, self.cfg, timeout=LIVE_MREZNI_ROK,
            on_update=prikaz,
            on_final=(
                (lambda raw: self._live_part(recorder, raw))
                if getattr(recorder, "live_insert", False) else None
            ),
        )

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
        if recorder.cancelled:
            return
        self._live_text = geministt.post_process(tekst, self.cfg).strip()
        self._live_text_dirty = True

    def _live_part(self, recorder, raw):
        if recorder.cancelled:
            return
        text = geministt.post_process(raw, self.cfg).strip()
        if text:
            self._deliver_live_part(recorder.ticket, text + " ", recorder.session)

    def _tick_live_panel(self):
        """Okvir sa prepisom uživo; sve se crta sa glavne niti."""
        # Zaustavljeno snimanje gasi okvir odmah, u sledecem otkucaju (50ms).
        # Reader jos radi i sme da posalje jos koju celinu — one idu u polje,
        # ali se vise ne crtaju.
        if self._live_off or (self._recorder is None and not self._starting):
            self._live_text_dirty = False
            self._live_text = ""
            if self.live_panel.visible:
                self.live_panel.hide()
            return

        if not (self._live_preview_on() and geministt.enabled(self.cfg)):
            return
        # Okvir izlazi odmah, sa „Slušam…", a ne tek uz prvi tekst. Server
        # ponekad celoj sesiji ne pošalje nijedan međurezultat (izmereno: 2 od
        # 11 sesija, isti kod i isti snimak), pa bi prvi znak života inače bio
        # tek potvrđena celina na pauzi, u istom trenutku kad se tekst upiše.
        if self._live_text_dirty or not self.live_panel.visible:
            self._live_text_dirty = False
            self.live_panel.set_text(self._live_text)
            if not self.live_panel.visible:
                self.live_panel.show(self._live_text)
