"""Google Web Speech: secenje na pauzama i segmenti koji se prepoznaju usput.

Endpoint prima najvise ~30 s po zahtevu, pa se dug diktat sece na pauzama i
svaki deo salje cim se odsece. Prepoznati delovi se ne upisuju odmah: idu u
okvir sa prepisom (kao kod Gemini Live), a u polje tek na Stop.
"""

import threading
import time
import traceback
from contextlib import nullcontext

from . import audio, polish, webstt


# Koliko se na Stop najduze ceka jedan deo koji se jos prepoznaje.
GOOGLE_ROK_DELA = 60


class GoogleTok:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

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
        recorder.google_delovi = []
        recorder.google_niti = []

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
                self._ship_segment(b"".join(frames), recorder, session)
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
        # Ceo diktat ide u polje odjednom: sacekaju se delovi koji se jos
        # prepoznaju, pa se spoje po redosledu snimanja.
        for nit in recorder.google_niti:
            nit.join(timeout=GOOGLE_ROK_DELA)
        delovi = [d for d in recorder.google_delovi if d] + ([text] if text else [])
        ceo = " ".join(d.strip() for d in delovi if d and d.strip())
        if session is not None:
            session.segment(session.next_index(), tail, text, kind="rep")
            session.finish(b"".join(everything), ceo)
        return ceo

    def _ship_segment(self, pcm: bytes, recorder, session=None):
        """Posalji odsecen deo na prepoznavanje, a snimanje ide dalje.

        Tekst dela ide u okvir, ne u polje: upis je tek na Stop.
        """
        delovi = recorder.google_delovi
        mesto = len(delovi)
        delovi.append(None)
        index = session.next_index() if session is not None else 0

        def work():
            text = ""
            try:
                text = self._recognize_or_keep(pcm)
                if not text:
                    # Ranije se ovo tiho gubilo — segment nestane bez traga.
                    print(f"[diktat] segment od {self._seconds(pcm):.1f}s nije prepoznat")
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                delovi[mesto] = (text or "").strip()
                if session is not None:
                    session.segment(index, pcm, text)
                self._google_preview(recorder)

        nit = threading.Thread(target=work, daemon=True)
        recorder.google_niti.append(nit)
        nit.start()

    def _google_preview(self, recorder):
        """Okvir pokazuje samo neprekinut pocetak: deo koji kasni ne pravi rupu."""
        gotovi = []
        for deo in recorder.google_delovi:
            if deo is None:
                break
            if deo:
                gotovi.append(deo)
        text = " ".join(gotovi).strip()
        with getattr(self, "_session_lock", nullcontext()):
            if (recorder.cancelled or recorder.zaustavljen
                    or self._recorder is not recorder or not text):
                return
            self._sacuvaj_prepis(recorder, text)
            self._live_text = text
            self._live_text_dirty = True
            self._live_last_update_at = time.monotonic()
            self._live_waiting = False
