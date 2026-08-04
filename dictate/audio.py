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

    # -- unutrasnji callback iz PortAudio niti --
    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        if self._stop.is_set():
            return
        data = bytes(indata)
        self._q.put(data)
        self._level = _peak(data)

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

    def stop(self):
        """Signalizira kraj — `chunks()` se posle ovoga zavrsi."""
        self._stop.set()
        self._q.put(None)

    def close(self):
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


def _peak(pcm: bytes) -> float:
    """Priblizan vrh amplitude bez numpy-ja — gleda svaki 16. sempl."""
    if not pcm:
        return 0.0
    top = 0
    for i in range(0, len(pcm) - 1, 32):
        val = int.from_bytes(pcm[i : i + 2], "little", signed=True)
        top = max(top, abs(val))
    return min(1.0, top / 32768.0)


def list_devices():
    return sd.query_devices()


def default_input_name():
    try:
        return sd.query_devices(kind="input")["name"]
    except Exception:  # noqa: BLE001
        return "nepoznat"
