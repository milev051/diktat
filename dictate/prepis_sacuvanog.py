"""Dugmad Prepisi i Obrisi za sacuvane snimke (rezerva.py).
"""

import threading
import traceback

from . import audio, geministt, insert, rezerva
from .pomoc import _short_error


class PrepisSacuvanog:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    def _aktivni_snimci(self):
        snimak = getattr(self._recorder, "snimak", None)
        return [snimak.putanja] if snimak is not None else []

    def sacuvani_snimci(self):
        return rezerva.sacuvani(aktivni=self._aktivni_snimci())

    def _prepisi_sacuvan(self, index: int):
        if self._prepis_radi:
            return
        sacuvani = self.sacuvani_snimci()
        if index >= len(sacuvani):
            return
        sacuvan = sacuvani[index]
        self._prepis_radi = True
        self.prepis_status = "Prepisujem…"
        self._sacuvani_dirty = True
        self.state.set(phase="thinking", message="Prepisujem sačuvan snimak…")

        def worker():
            try:
                pcm, _rate = sacuvan.procitaj()
                tekst = self._prepisi_pcm(pcm).strip()
                if not tekst:
                    self.prepis_status = "U snimku nije prepoznat govor."
                    self.state.set(phase="idle", message="")
                    return
                insert.set_clipboard(tekst)
                self._remember(tekst)
                sacuvan.obrisi()
                self.state.set(phase="idle", message="")
                self.prepis_status = "Prepis je u clipboard-u i u istoriji. Nalepi ga sa ⌘V."
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self.prepis_status = f"Prepis nije uspeo: {_short_error(exc)}"
                self.state.set(phase="idle", message="")
            finally:
                self._prepis_radi = False
                self._sacuvani_dirty = True

        threading.Thread(target=worker, daemon=True).start()

    def _prepisi_pcm(self, pcm: bytes) -> str:
        """Ceo snimak kroz izabran servis, bez mikrofona.

        Google prima najvise ~30 s po zahtevu, pa se snimak sece na pauzama,
        isto kao u neprekidnom rezimu. Gemini i OpenAI primaju ceo snimak.
        """
        if (self.cfg.get("transcription_provider", "google") == "openai"
                or geministt.enabled(self.cfg)):
            return self._apply_rules(self._recognize(pcm))
        rate = int(self.cfg["sample_rate"])
        korak = rate // 10 * 2
        detektor = audio.PauseDetector(pause_seconds=float(self.cfg.get("pause_seconds", 0.7)))
        granica = float(self.cfg.get("max_request_seconds", 30))
        delovi, tekuci, sekundi = [], [], 0.0
        for i in range(0, len(pcm), korak):
            komad = pcm[i:i + korak]
            tekuci.append(komad)
            sekundi += len(komad) / 2 / rate
            pauza = detektor.feed(audio.peak(komad), len(komad) / 2 / rate)
            if (pauza and sekundi >= 15) or sekundi >= granica:
                delovi.append(self._recognize(b"".join(tekuci)))
                tekuci, sekundi = [], 0.0
                detektor.reset()
        if tekuci:
            delovi.append(self._recognize(b"".join(tekuci)))
        return " ".join(d.strip() for d in delovi if d and d.strip())
