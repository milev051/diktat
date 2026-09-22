"""Upis teksta u aktivno polje, strogo po redosledu snimanja, i istorija.
"""

import traceback
from collections import deque

from . import config, insert


class Upis:
    """Deo DictateApp-a; stanje drzi DictateApp.__init__."""

    def _next_ticket(self, session: int) -> int:
        """Redni broj za ubacivanje.

        Dodeljuje se u trenutku kad se AUDIO tog segmenta zavrsi, ne kad se
        prepoznavanje zavrsi. Posto mikrofon moze da snima samo jedno po jedno,
        taj redosled je uvek hronoloski — pa tekst stigne onako kako si govorio.
        """
        with self._count_lock:
            self._ticket += 1
            self._pending += 1
            self._pending_by[session] = self._pending_by.get(session, 0) + 1
            return self._ticket

    def _deliver(self, ticket: int, text: str, session: int):
        self._insert_q.put((ticket, text, session, False))

    def _deliver_live_part(self, ticket: int, text: str, session: int):
        if text.strip():
            self._insert_q.put((ticket, text, session, True))

    def _insert_worker(self):
        """Lepi tekst strogo po redosledu snimanja.

        Prepoznavanja teku paralelno i mogu da se zavrse van reda — kratak
        drugi snimak lako stigne pre dugog prvog. Ovde se ceka na red.
        """
        buffered = {}
        expected = 1
        while True:
            seq, text, sesija, partial = self._insert_q.get()
            buffered.setdefault(seq, deque()).append((text, sesija, partial))
            while expected in buffered:
                events = buffered[expected]
                if not events:
                    break
                ready, cija, is_partial = events.popleft()
                if is_partial:
                    try:
                        insert.insert_live(ready)
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
                    continue
                del buffered[expected]
                expected += 1
                with self._count_lock:
                    if self._pending > 0:
                        self._pending -= 1
                    if self._pending_by.get(cija, 0) > 0:
                        self._pending_by[cija] -= 1
                if ready and self._deferred():
                    # Ceka se ceo diktat: model treba da vidi pun kontekst.
                    with self._formal_lock:
                        self._formal_parts.setdefault(cija, []).append(ready.strip())
                elif ready:
                    self._remember(ready)
                    try:
                        insert.insert(
                            ready,
                            method=self.cfg.get("insert_method", "auto"),
                            restore_clipboard=self.cfg.get("restore_clipboard", True),
                        )
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
            self._maybe_polish()
            self._settle_phase()

    def _remember(self, text: str):
        """Zapamti ubacen tekst. Zove se iz radne niti, pa meni ne dira —
        samo podigne zastavicu koju _tick pokupi na glavnoj niti."""
        clean = text.strip()
        if not clean:
            return
        # Istorija je namerno kratka da meni ostane pregledan. Stari config.json
        # Istorija je kratka, ali ista na desktopu i telefonu.
        size = max(1, min(int(self.cfg.get("history_size", 5)), 5))
        with self._hist_lock:
            if clean in self._history:
                self._history.remove(clean)
            self._history.insert(0, clean)
            del self._history[size:]
        config.save(self.cfg)
        self._history_dirty = True
