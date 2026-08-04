"""Snimanje sa mikrofona u 16-bit PCM komadima."""

import queue
import threading
import time

import sounddevice as sd

BLOCK_MS = 100


class Recorder:
    """Otvara mikrofon i izbacuje sirove PCM bajtove kroz `chunks()`."""

    def __init__(self, sample_rate=16000, device=None, max_seconds=290):
        self.sample_rate = sample_rate
        self.device = device
        self.max_seconds = max_seconds
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._stream = None
        self._level = 0.0
        # Postavlja ih app.py; drze se po snimku jer vise sesija moze da tece paralelno.
        self.cancelled = False
        self.released = False
        self.ticket = 0
        self._tail_timer = None

    # -- unutrasnji callback iz PortAudio niti --
    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        if self._stop.is_set():
            return
        data = bytes(indata)
        self._q.put(data)
        self._level = peak(data)

    def start(self):
        blocksize = int(self.sample_rate * BLOCK_MS / 1000)
        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=blocksize,
            device=self.device,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self, tail=0.0):
        """Zavrsi snimanje, ali tek posle `tail` sekundi.

        Bez repa se gubi poslednja rec: PortAudio isporucuje zvuk u blokovima
        od BLOCK_MS, pa blok koji je u tom trenutku u letu biva odbacen — a
        korisnik ionako pusta taster tacno na kraju poslednje reci.
        """
        if tail > 0 and not self._stop.is_set():
            if self._tail_timer is None:
                self._tail_timer = threading.Timer(tail, self._finish)
                self._tail_timer.daemon = True
                self._tail_timer.start()
            return
        self._finish()

    def _finish(self):
        self._stop.set()
        self._q.put(None)

    def close(self):
        if self._tail_timer is not None:
            self._tail_timer.cancel()
            self._tail_timer = None
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001 - zatvaranje ne sme da obori sesiju
                pass
            self._stream = None

    @property
    def level(self) -> float:
        """Trenutna jacina signala, 0.0-1.0 — za indikator u overlay-u."""
        return self._level

    def chunks(self):
        """Generator PCM bajtova; zavrsava se na stop() ili max_seconds."""
        deadline = time.monotonic() + self.max_seconds
        while True:
            if time.monotonic() > deadline:
                return
            try:
                item = self._q.get(timeout=0.25)
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            if item is None:
                return
            yield item


def peak(pcm: bytes) -> float:
    """Priblizan vrh amplitude bez numpy-ja — gleda svaki 16. sempl."""
    if not pcm:
        return 0.0
    top = 0
    for i in range(0, len(pcm) - 1, 32):
        val = int.from_bytes(pcm[i : i + 2], "little", signed=True)
        top = max(top, abs(val))
    return min(1.0, top / 32768.0)


_peak = peak   # stari naziv, koristi se u testovima


class PauseDetector:
    """Prepoznaje pauzu u govoru, sa pragom koji se sam prilagodjava sobi.

    Fiksni prag ne valja: u tihoj sobi je nivo pozadine ~0.01, u bucnoj ~0.08.
    Zato se prati "pod" (najtisi nivo do sada) i pauzom se smatra sve ispod
    `factor` puta tog poda.
    """

    FLOOR_DOWN = 0.30      # pod brzo pada ka novom minimumu
    FLOOR_UP = 0.002       # a vrlo sporo raste, da govor ne podigne prag
    PEAK_DECAY = 0.999     # vrh polako splasnjava
    PEAK_FRACTION = 0.25   # prag nikad iznad ovoga puta vrh

    def __init__(self, pause_seconds=0.7, factor=2.5, floor_min=0.015):
        self.pause_seconds = pause_seconds
        self.factor = factor
        self.floor_min = floor_min
        self.floor = None
        self.peak = None
        self.quiet_for = 0.0
        self.heard_speech = False

    def reset(self):
        self.quiet_for = 0.0
        self.heard_speech = False

    @property
    def threshold(self) -> float:
        base = self.floor if self.floor is not None else 0.0
        low = max(self.floor_min, base * self.factor)
        if self.peak is None:
            return low
        # Bez ove kapice: ako snimanje pocne usred reci, pod se inicijalizuje
        # na nivo govora, prag odleti iznad svega i nijedna pauza se ne prizna.
        return min(low, max(self.floor_min, self.peak * self.PEAK_FRACTION))

    def feed(self, level: float, dt: float) -> bool:
        """Ubaci nivo jednog komada. Vraca True kad pauza dostigne prag."""
        self.peak = level if self.peak is None else max(level, self.peak * self.PEAK_DECAY)

        if self.floor is None:
            self.floor = level
        elif level < self.floor:
            self.floor += (level - self.floor) * self.FLOOR_DOWN
        else:
            self.floor += (level - self.floor) * self.FLOOR_UP

        if level < self.threshold:
            self.quiet_for += dt
        else:
            self.quiet_for = 0.0
            self.heard_speech = True

        # Bez ovoga bi duza tisina okidala u nedogled i slala prazne segmente.
        return self.heard_speech and self.quiet_for >= self.pause_seconds


def list_devices():
    return sd.query_devices()


def default_input_name():
    try:
        return sd.query_devices(kind="input")["name"]
    except Exception:  # noqa: BLE001
        return "nepoznat"
