"""Snimanje: start, stop, osigurac, jedna sesija diktata i izbor servisa.

Mikrofon cita zasebna nit (`_tracked`), pa STOP ne zavisi od mreze. Sama
sesija (`_run_session`) odlucuje sta ide u upis, sta u gresku, a sta u
rezervni snimak.
"""

import queue
import threading
import time
import traceback

from . import audio, config, geministt, rezerva
from .pomoc import _short_error

# Koliko posle repa STOP sme da ceka pre nego sto osigurac oslobodi mikrofon.
STOP_ROK = 3.0


class Snimanje:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    def _stop_from_menu(self, _):
        self._on_stop()
        # Prekidac se vraca u mirovanje odmah: `_release_recorder` to radi tek
        # kad rep istekne, a dotle bi pritisak tastera radio STOP nad snimanjem
        # koje se vec zaustavlja.
        listener = getattr(self, "listener", None)
        if listener is not None:
            listener.reset()
        self._sync_stop_item()

    def _await_slot(self) -> bool:
        """Sacekaj da se mikrofon oslobodi.

        Posle pustanja tastera snimanje jos traje `tail_seconds`, pa bi pritisak
        odmah zatim bio tiho progutan — a bas tako se i koristi: stanes, pa
        odmah krenes ponovo dok se prethodni tekst jos obradjuje.
        """
        deadline = time.monotonic() + float(self.cfg.get("tail_seconds", 0.8)) + 0.7
        while True:
            with self._session_lock:
                if self._recorder is None:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.03)

    def _on_start(self):
        """Vraca False ako snimanje nije poceto — hotkey tada vrati svoje stanje."""
        self._live_off = False
        with self._session_lock:
            self._starting += 1
            self._stop_requested = False
        try:
            return self._start_recording()
        finally:
            with self._session_lock:
                self._starting -= 1

    def _start_recording(self):
        if not self._await_slot():
            return False
        with self._session_lock:
            if self._recorder is not None:
                return False
            # Lista uredjaja se osvezava pred svaki diktat (~2ms) — bez toga
            # PortAudio i dalje gleda uredjaje od pre vadjenja slusalica.
            audio.refresh_devices()
            recorder = audio.Recorder(
                sample_rate=self.cfg["sample_rate"],
                device=self.cfg.get("input_device"),
                max_seconds=self._limit_seconds(),
            )
            try:
                recorder.start()
            except Exception as exc:  # noqa: BLE001
                self.state.set(phase="error", message=f"Mikrofon: {exc}")
                return False
            recorder.session = self._nova_sesija(zakljucano=True)
            recorder.snimak = (
                rezerva.Snimak.novi(int(self.cfg["sample_rate"]))
                if self.cfg.get("rezervni_snimak", True) else None
            )
            self._recorder = recorder
            recorder.live_insert = (
                geministt.enabled(self.cfg)
                and bool(self.cfg.get("gemini_live_insert", False))
                and self.cfg.get("insert_method", "auto") != "clipboard_only"
            )
            self._record_started_at = time.monotonic()
            recorder.pokrenuto = self._record_started_at
            # Faza se upisuje pod katancem, da je _settle_phase prethodne
            # sesije ne prepise natrag na "obradjuje".
            self.state.set(phase="recording", message="")
            # STOP koji je stigao dok se mikrofon jos otvarao ne sme da propadne.
            propusteni_stop = self._stop_requested
            self._stop_requested = False

        if recorder.live_insert:
            # Živi delovi moraju da zauzmu mesto u istom redu kao ostali
            # diktati pre nego što prvi od njih stigne sa servera.
            recorder.ticket = self.upis.novi_tiket(recorder.session)
        threading.Thread(target=self._run_session, args=(recorder,), daemon=True).start()
        if propusteni_stop:
            self._on_stop()
        return True

    def _on_stop(self):
        with self._session_lock:
            recorder = self._recorder
            if recorder is None and self._starting:
                # Snimanje se jos otvara; zapamti STOP da ga pokretanje pokupi.
                self._stop_requested = True
                return
        if recorder is None:
            return
        self.state.set(phase="thinking")
        # Okvir sa prepisom nestaje odmah, ne kad rep istekne: snimanje je za
        # korisnika gotovo u trenutku kad pusti taster.
        self._live_off = True
        # Rep hvata poslednju rec — taster se pusta tacno na njenom kraju.
        rep = float(self.cfg.get("tail_seconds", 0.8))
        recorder.stop(tail=rep)
        cuvar = threading.Timer(rep + STOP_ROK, self._cuvar_zaustavljanja, args=(recorder,))
        cuvar.daemon = True
        cuvar.start()

    def _cuvar_zaustavljanja(self, recorder):
        """STOP mora da zaustavi sat, sta god da se zaglavilo iza njega.

        Posle odvajanja mikrofona od mreze (`_tracked`) ovo ne bi smelo da se
        desi. Ostaje kao osigurac: ako PortAudio zapne pri zatvaranju strima ili
        se pojavi neki treci uzrok, korisnik ne sme da gleda sat koji tece i
        taster koji ne reaguje. Linija u logu kaze da je osigurac radio, pa se
        uzrok trazi odatle.
        """
        with self._session_lock:
            if self._recorder is not recorder or recorder.released:
                return
            self._recorder = None
        print(f"[diktat] snimanje nije stalo {STOP_ROK:.0f}s posle STOP-a, "
              "oslobadjam mikrofon silom", flush=True)
        recorder._finish()
        listener = getattr(self, "listener", None)
        if listener is not None:
            listener.reset(pokrenuto=getattr(recorder, "pokrenuto", None))
        # Zatvaranje strima je upravo ono sto ume da zapne, pa ide u svoju nit.
        threading.Thread(target=self._release_recorder, args=(recorder,),
                         daemon=True).start()
        self._settle_phase()

    def _on_cancel(self, reason="otkazano"):
        with self._session_lock:
            recorder = self._recorder
            if recorder is None:
                return
            recorder.cancelled = True
        self._live_off = True
        recorder.stop()
        self._settle_phase(reason)

    def _limit_seconds(self) -> float:
        """Koliko sme da traje JEDAN pritisak tastera."""
        if geministt.enabled(self.cfg):
            # Live je jedini izvor koji salje zvuk DOK snimas (~2,5 MB/min), pa
            # zaboravljen diktat tu curi podatke sve vreme, a ne tek na kraju.
            # Zato kratka granica: posle nje se trazi nov pritisak.
            try:
                limit = int(self.cfg.get("gemini_live_max_seconds", 120))
            except (TypeError, ValueError):
                limit = 120
            return float(min(3600, max(30, limit)))
        if self.cfg.get("transcription_provider", "google") == "openai":
            if self._openai_long_recording():
                try:
                    limit = int(self.cfg.get("openai_max_seconds", 3600))
                except (TypeError, ValueError):
                    limit = 3600
                return float(min(3600, max(60, limit)))
            return float(self.cfg.get("max_request_seconds", 30))
        if self._segmenting():
            # Segmenti drze pojedinacne zahteve kratkim, pa granica sluzi samo
            # da zaboravljen diktat jednom stane.
            return float(self.cfg.get("continuous_max_seconds", 3600))
        return float(self.cfg.get("max_request_seconds", 30))

    def _segmenting(self) -> bool:
        return bool(self.cfg.get("continuous", True)) or bool(
            self.cfg.get("auto_segment", False)
        )

    def _nova_sesija(self, zakljucano=False) -> int:
        """Nov redni broj diktata. `zakljucano` znaci da katanac vec drzimo."""
        if zakljucano:
            self._session_seq += 1
            return self._session_seq
        with self._session_lock:
            self._session_seq += 1
            return self._session_seq

    def _release_recorder(self, recorder):
        """Audio je gotov: pusti mikrofon ODMAH da moze sledeci diktat,
        dok prepoznavanje ovog jos traje u pozadini."""
        if recorder.released:
            return
        recorder.released = True
        # Strim se zatvara PRE oslobadjanja slota: sledeci diktat reinicijalizuje
        # PortAudio, a to ne sme da se desi dok je neki strim jos otvoren.
        # Ticket se uzima dok slot jos drzimo, da nova sesija ne preuzme nizi broj.
        recorder.close()
        if not recorder.ticket:
            recorder.ticket = self.upis.novi_tiket(recorder.session)
        with self._session_lock:
            if self._recorder is recorder:
                self._recorder = None
        # Prekidac se vraca u mirovanje: ako se snimanje samo prekinulo na
        # granici, sledeci pritisak mora da POKRENE, a ne da zaustavi. Ali samo
        # ako pritisak pripada OVOM snimanju; onaj koji je vec pokrenuo sledece
        # snimanje ostaje, inace to snimanje ne moze da se zaustavi tasterom.
        listener = getattr(self, "listener", None)
        if listener is not None:
            listener.reset(pokrenuto=getattr(recorder, "pokrenuto", None))
        if recorder.hit_limit:
            print(f"[diktat] granica od {self._limit_seconds():.0f}s — snimanje prekinuto")
        if recorder.captured == 0:
            # Strim se otvorio ali nije stigao nijedan sempl — uredjaj je
            # najverovatnije nestao pod nogama. Sledeci put krece iz cista.
            print("[diktat] nijedan sempl nije stigao, osvezavam audio uredjaje")
            audio.refresh_devices()

    def _settle_phase(self, message=""):
        """Ne gasi ekran ako je u medjuvremenu poceo nov diktat.

        Provera i upis idu pod istim katancem koji drzi i _on_start: inace se
        moze ubaciti izmedju, videti mikrofon jos slobodan, pa prepisati
        "snima" preko "obradjuje" iako je nov diktat vec poceo.
        """
        with self._session_lock:
            if self._recorder is not None:
                return
            busy = self.upis.na_cekanju() > 0
            if self.ceka_obradu.radi():
                return                      # cekamo model, ne gasi prikaz
            self.state.set(phase="thinking" if busy else "idle", message=message)

    def _tracked(self, recorder):
        """Mikrofon i mreza su odvojeni: zvuk cita zasebna nit.

        Ranije je mikrofon citao onaj ko salje na mrezu. Kad Gemini Live
        prestane da prima (izmereno 22.09.2026: „Isteklo vreme cekanja
        odgovora"), slanje stoji, pa niko ne cita mikrofon: snimanje se ne
        zavrsava, `_recorder` ostaje zauzet i taster deluje mrtav do isteka
        mreznog roka. Sada nit pumpe prazni mikrofon nezavisno od mreze, pise
        rezervnu kopiju i pusta mikrofon cim snimanje stane.
        """
        red: queue.Queue = queue.Queue()
        snimak = getattr(recorder, "snimak", None)

        def pumpa():
            try:
                for komad in recorder.chunks():
                    if snimak is not None:
                        snimak.upisi(komad)
                    red.put(komad)
            finally:
                if snimak is not None:
                    snimak.zatvori()
                self._release_recorder(recorder)
                red.put(None)

        threading.Thread(target=pumpa, name="diktat-mikrofon", daemon=True).start()
        try:
            while True:
                komad = red.get()
                if komad is None:
                    return
                yield komad
        finally:
            # Potrosac je odustao (pala mreza): mikrofon mora da stane i sam.
            recorder.stop()

    def _run_session(self, recorder):
        text = ""
        error = None
        try:
            text = self._transcribe(recorder)
        except Exception as exc:  # noqa: BLE001
            error = _short_error(exc)
            traceback.print_exc()
        finally:
            self._add_recorded_seconds(
                recorder.captured / 2 / float(self.cfg.get("sample_rate", 16000))
            )
            self._release_recorder(recorder)

        # Rezervni snimak ostaje samo kad prepis nije stigao; uspeo diktat ga
        # brise odmah, da glas ne stoji na disku bez razloga.
        # Gemini Live na tisinu ne vrati nista, pa bi slucajan pritisak izlazio
        # kao greska i kao sacuvan snimak; `rezerva.ishod` to razlikuje.
        snimak = getattr(recorder, "snimak", None)
        if snimak is not None:
            obrisi, nova_greska = rezerva.ishod(text, error, snimak.vrh, recorder.cancelled)
            if error and not nova_greska:
                print(f"[diktat] tisina (vrh {snimak.vrh:.3f}), greska se ne prijavljuje: {error}",
                      flush=True)
            error = nova_greska
            if obrisi:
                snimak.obrisi()
        sacuvan = snimak is not None and snimak.putanja.exists()
        if sacuvan:
            self._sacuvani_dirty = True

        # Ticket dodeljen u _release_recorder mora da se preda tacno jednom,
        # inace red ubacivanja stane zauvek.
        ticket = recorder.ticket
        if recorder.cancelled or error:
            self.upis.predaj(ticket, "", recorder.session)
            if error and not recorder.cancelled:
                if sacuvan:
                    error = f"{error[:120]} · snimak je sačuvan u Podešavanjima"
                self.state.set(phase="error", message=error)
            else:
                self._settle_phase()
            return

        if getattr(recorder, "live_insert", False):
            if text.strip():
                self.upis.zapamti(text)
            self.upis.predaj(ticket, "", recorder.session)
            return

        text = text.strip()
        if not text:
            self.upis.predaj(ticket, "", recorder.session)
            self._settle_phase("(nista)")
            return

        text = self._finish(text)
        if not self._deferred():
            debug_session = self._debug_sessions.pop(recorder.session, None)
            if debug_session is not None:
                debug_session.final(text)
        self.upis.predaj(ticket, text, recorder.session)

    def _finish(self, text: str) -> str:
        # Razmak na kraju je uvek: bez njega se recenice slepe pri nadovezivanju.
        return text + " "

    def _transcribe(self, recorder):
        """Svaki servis ima svoj tok: tok_openai.py, tok_gemini.py, tok_google.py."""
        if self.cfg.get("transcription_provider", "google") == "openai":
            return self._transcribe_whole(recorder, "openai")
        if geministt.enabled(self.cfg):
            return self._transcribe_live(recorder)
        return self._transcribe_google(recorder)

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

    def _recognize(self, pcm: bytes) -> str:
        """Ceo snimak (ili segment) kroz izabran servis."""
        if not pcm:
            return ""
        if self.cfg.get("transcription_provider", "google") == "openai":
            return self._recognize_openai(pcm)
        if geministt.enabled(self.cfg):
            return self._recognize_gemini(pcm)
        return self._recognize_google(pcm)

    @staticmethod
    def _seconds(pcm: bytes, rate=16000) -> float:
        return len(pcm) / 2 / rate

    def _recorded_seconds(self) -> float:
        try:
            return max(0.0, float(self.cfg.get("recorded_seconds", 0.0)))
        except (TypeError, ValueError):
            return 0.0

    def _add_recorded_seconds(self, seconds: float):
        if seconds <= 0:
            return
        with self._stats_lock:
            self.cfg["recorded_seconds"] = self._recorded_seconds() + seconds
            config.save(self.cfg)
