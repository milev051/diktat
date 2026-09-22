"""Google Web Speech: secenje na pauzama i segmenti koji se prepoznaju usput.

Endpoint prima najvise ~30 s po zahtevu, pa se dug diktat sece na pauzama i
svaki deo salje cim se odsece. Redosled cuvaju tiketi (`upis.py`).
"""

import threading
import traceback

from . import audio, polish, rezerva, webstt


class GoogleTok:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    # Ispod ovog vrha amplitude nema govora: tiha soba je ~0.01, bucna ~0.08.
    # Prazan prepis tise od toga je stvarno tisina, ne izgubljen deo diktata.
    GOVOR_PEAK = 0.10

    GOVOR_SEKUNDI = 1.0

    def _bilo_je_govora(self, pcm: bytes) -> bool:
        """Gruba provera da snimak nije puka tisina."""
        return (
            self._seconds(pcm) >= self.GOVOR_SEKUNDI
            and audio.peak(pcm) >= self.GOVOR_PEAK
        )

    def _recognize_or_keep(self, pcm: bytes) -> str:
        """Prepis segmenta; prazan rezultat za jasan govor se samo prijavi.

        Ispis u logu je trag da deo diktata nije stigao. Zvuk celog diktata
        ostaje u rezervnom snimku (`rezerva.py`) dok prepis ne uspe.
        """
        text = self._recognize(pcm)
        if not text and self._bilo_je_govora(pcm):
            print(
                f"[diktat] prazan prepis za {self._seconds(pcm):.1f}s govora"
            )
        return text

    def _recognize_google(self, pcm: bytes) -> str:
        text, _conf = webstt.recognize_full(
            pcm,
            language=self.cfg.get("language", "sr-RS"),
            sample_rate=self.cfg["sample_rate"],
            key=self.cfg.get("api_key") or None,
        )
        if not text:
            return text
        if self._formal() and polish.tidy_on(self.cfg):
            # Kad model sredjuje tekst, dobija ga kakav jeste:
            # skracenice i skidanje kvacica bi mu otezali citanje. Pravila se
            # tada primenjuju na kraju, nad ispravljenim tekstom.
            return text
        return self._apply_rules(text)

    def _transcribe_google(self, recorder):
        """Na dugom diktatu sece snimak na pauzama i salje delove na obradu
        dok ti jos pricas, pa nema cekanja na kraju."""
        if not self._segmenting():
            session = self._dump.session() if self._dump else None
            if session is not None:
                self._debug_sessions[recorder.session] = session
            pcm = b"".join(self._tracked(recorder))
            if recorder.cancelled:
                return ""
            self._settle_phase()
            text = self._recognize_or_keep(pcm)
            if session is not None:
                session.segment(session.next_index(), pcm, text, kind="ceo")
                session.finish(pcm, text)
            return text

        detector = audio.PauseDetector(
            pause_seconds=float(self.cfg.get("pause_seconds", 0.7))
        )
        cut_after = float(self.cfg.get("segment_after_seconds", 15))
        hard_cut = float(self.cfg.get("max_request_seconds", 30))
        rate = self.cfg["sample_rate"]

        session = self._dump.session() if self._dump else None
        if session is not None:
            self._debug_sessions[recorder.session] = session
        everything: list[bytes] = []
        frames: list[bytes] = []
        seconds = 0.0

        for chunk in self._tracked(recorder):
            frames.append(chunk)
            if session is not None:
                everything.append(chunk)
            step = len(chunk) / 2 / rate
            # Duzina segmenta se meri PO ZVUKU, ne po zidnom satu. max_request_seconds
            # je granica koliko sekundi zvuka endpoint prima, pa ta dva moraju da
            # budu ista mera i onda kad potrosac kasni za mikrofonom.
            seconds += step
            # Nivo se racuna IZ OVOG komada. `recorder.level` je nivo poslednjeg
            # uhvacenog komada — detektor bi gledao jedan zvuk a sekao drugi.
            paused = detector.feed(audio.peak(chunk), step)
            # Tvrdi rez postoji jer endpoint puca na zahtevima duzim od ~30s,
            # a neko moze da prica bez ijedne pauze.
            if frames and ((paused and seconds >= cut_after) or seconds >= hard_cut):
                self._ship_segment(b"".join(frames), recorder.session, session)
                frames = []
                seconds = 0.0
                detector.reset()

        if recorder.cancelled:
            return ""
        self._settle_phase()
        tail = b"".join(frames)
        text = self._recognize_or_keep(tail)
        if not text and self._seconds(tail) > 0.4:
            print(f"[diktat] rep od {self._seconds(tail):.1f}s nije prepoznat")
        if session is not None:
            session.segment(session.next_index(), tail, text, kind="rep")
            session.finish(b"".join(everything), text)
        return text

    def _ship_segment(self, pcm: bytes, sesija: int, session=None):
        """Posalji odsecen deo na prepoznavanje, a snimanje ide dalje."""
        ticket = self._next_ticket(sesija)
        index = session.next_index() if session is not None else 0

        def work():
            text = ""
            try:
                text = self._recognize_or_keep(pcm)
                if not text:
                    # Ranije se ovo tiho gubilo — segment nestane bez traga.
                    print(f"[diktat] segment od {self._seconds(pcm):.1f}s nije prepoznat")
                if text:
                    text = self._finish(text)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                if session is not None:
                    session.segment(index, pcm, text)
                self._deliver(ticket, text, sesija)

        threading.Thread(target=work, daemon=True).start()
