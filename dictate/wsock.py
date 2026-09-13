"""Najmanji mogući WebSocket klijent (RFC 6455), samo za Gemini Live API.

Zašto ručno a ne `websockets`: ceo projekat priča sa mrežom preko `urllib`, bez
ijedne dodatne zavisnosti — ADTS zaglavlje i multipart telo su isto tako pisani
rukom. Live API nam treba samo za jedan tok: pošalji JSON okvire, čitaj JSON
okvire, zatvori. To je stotinak linija, a `websockets` bi uvukao asyncio u kod
koji je ceo sinhron i nitima vođen.

Podržano je tačno ono što taj tok traži: tekstualni okviri, nastavak okvira
(continuation), odgovor na ping, uredno zatvaranje. Nema kompresije (ne tražimo
`permessage-deflate`) ni podele slanja na više okvira.
"""

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
from urllib.parse import urlsplit

# Fiksna konstanta iz RFC 6455; služi samo za proveru odgovora na rukovanje.
# Prekucava se lako pogrešno (poslednje dve grupe), a greška se vidi tek kao
# „Pogrešan Sec-WebSocket-Accept" nad ispravnim 101 odgovorom — zato test nad
# vektorom iz samog RFC-a, a ne nad nasumičnim ključem.
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WebSocketError(Exception):
    """Greška veze; `retryable` znači da drugi pokušaj ima smisla."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class WebSocketTimeout(WebSocketError):
    """Kratko čekanje bez novih podataka; veza je i dalje otvorena."""


class WebSocket:
    """Sinhroni klijent. Koristi se kao kontekst, da se utičnica uvek zatvori."""

    def __init__(self, url, timeout=30.0, headers=None):
        self._url = url
        self._timeout = timeout
        self._headers = dict(headers or {})
        self._sock = None
        self._buf = b""
        self._closed = False
        self._send_lock = threading.Lock()
        self._fragments = []
        self._fragment_opcode = None
        # Razlog zatvaranja stize u CLOSE okviru i JEDINI je trag zasto je
        # sesija pala ("API key not valid", "quota exceeded"). Bez ovoga bi
        # pozivalac video samo prazno citanje i prijavio "zatvoreno bez razloga".
        self.close_code = None
        self.close_reason = ""

    # ------------------------------------------------------------ rukovanje

    def connect(self):
        parts = urlsplit(self._url)
        if parts.scheme not in ("ws", "wss"):
            raise WebSocketError(f"Nepodržana šema: {parts.scheme}", retryable=False)
        secure = parts.scheme == "wss"
        host = parts.hostname
        port = parts.port or (443 if secure else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        try:
            raw = socket.create_connection((host, port), timeout=self._timeout)
            if secure:
                ctx = ssl.create_default_context()
                raw = ctx.wrap_socket(raw, server_hostname=host)
            raw.settimeout(self._timeout)
        except OSError as exc:
            raise WebSocketError(f"Ne mogu da se povežem: {exc}") from exc
        self._sock = raw

        kljuc = base64.b64encode(os.urandom(16)).decode("ascii")
        redovi = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}" if port in (80, 443) else f"Host: {host}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {kljuc}",
            "Sec-WebSocket-Version: 13",
        ]
        redovi.extend(f"{k}: {v}" for k, v in self._headers.items())
        zahtev = ("\r\n".join(redovi) + "\r\n\r\n").encode("ascii")
        self._send_all(zahtev)
        self._check_handshake(kljuc)
        return self

    def _check_handshake(self, kljuc):
        zaglavlje = self._read_until(b"\r\n\r\n")
        tekst = zaglavlje.decode("latin-1", "replace")
        prva = tekst.split("\r\n", 1)[0]
        if " 101" not in prva:
            # 4xx nosi razlog u telu, ali ga ovde nemamo pouzdano — status je
            # dovoljan da se razlikuje mrtav ključ (ponavljanje nema smisla)
            # od prolazne smetnje.
            kod = prva.split(" ")[1] if len(prva.split(" ")) > 1 else "?"
            raise WebSocketError(
                f"Rukovanje odbijeno: {prva.strip()}",
                retryable=kod not in ("400", "401", "403", "404"),
            )
        ocekivano = base64.b64encode(
            hashlib.sha1((kljuc + GUID).encode("ascii")).digest()
        ).decode("ascii")
        for red in tekst.split("\r\n")[1:]:
            ime, _, vrednost = red.partition(":")
            if ime.strip().lower() == "sec-websocket-accept":
                if vrednost.strip() != ocekivano:
                    raise WebSocketError("Pogrešan Sec-WebSocket-Accept", retryable=False)
                return
        raise WebSocketError("Nema Sec-WebSocket-Accept u odgovoru", retryable=False)

    # ------------------------------------------------------------ slanje

    def send_json(self, poruka):
        self.send_text(json.dumps(poruka))

    def send_text(self, tekst):
        self._send_frame(OP_TEXT, tekst.encode("utf-8"))

    def _send_frame(self, opcode, payload):
        if self._sock is None:
            raise WebSocketError("Veza nije otvorena", retryable=False)
        # Live prikaz čita i šalje u različitim nitima; PONG iz čitača ne sme
        # da se umeša u sred audio okvira koji šalje druga nit.
        with self._send_lock:
            self._send_all(encode_frame(opcode, payload))

    def _send_all(self, data):
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise WebSocketError(f"Slanje nije uspelo: {exc}") from exc

    # ------------------------------------------------------------ prijem

    def recv_json(self):
        """Sledeća JSON poruka, ili None kad druga strana zatvori vezu."""
        tekst = self.recv_text()
        if tekst is None:
            return None
        try:
            return json.loads(tekst)
        except json.JSONDecodeError as exc:
            raise WebSocketError(f"Odgovor nije JSON: {exc}") from exc

    def recv_text(self):
        """Sastavi jednu poruku iz okvira; None znači da je veza zatvorena.

        Ping se odgovara u hodu — server ume da ga pošalje usred toka, a bez
        pong-a nas posle nekog vremena isključi.
        """
        while True:
            fin, opcode, payload = self._recv_frame()
            if opcode == OP_CLOSE:
                self._closed = True
                if len(payload) >= 2:
                    self.close_code = struct.unpack("!H", payload[:2])[0]
                    self.close_reason = payload[2:].decode("utf-8", "replace")
                return None
            if opcode == OP_PING:
                self._send_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CONT:
                if self._fragment_opcode is None:
                    raise WebSocketError("Nastavak okvira bez početka", retryable=False)
            else:
                self._fragment_opcode = opcode
            self._fragments.append(payload)
            if fin:
                # Live API ume da isti JSON pošalje i kao tekstualni i kao
                # binarni okvir, pa se oba dekodiraju isto.
                tekst = b"".join(self._fragments).decode("utf-8", "replace")
                self._fragments = []
                self._fragment_opcode = None
                return tekst

    def _recv_frame(self):
        # Ne troši zaglavlje dok ne stigne ceo okvir. Kratak timeout tokom
        # prikaza uživo može da padne usred payload-a; sledeći poziv tada mora
        # da nastavi isti okvir, ne da njegove bajtove protumači kao zaglavlje.
        self._read_at_least(2)
        fin = bool(self._buf[0] & 0x80)
        opcode = self._buf[0] & 0x0F
        maskirano = bool(self._buf[1] & 0x80)
        duzina = self._buf[1] & 0x7F
        offset = 2
        if duzina == 126:
            self._read_at_least(offset + 2)
            duzina = struct.unpack("!H", self._buf[offset:offset + 2])[0]
            offset += 2
        elif duzina == 127:
            self._read_at_least(offset + 8)
            duzina = struct.unpack("!Q", self._buf[offset:offset + 8])[0]
            offset += 8
        if maskirano:
            # Server nikad ne maskira; ako maskira, protokol je prekršen.
            self._read_at_least(offset + 4)
            kljuc = self._buf[offset:offset + 4]
            offset += 4
            self._read_at_least(offset + duzina)
            payload = _mask(self._buf[offset:offset + duzina], kljuc)
        else:
            self._read_at_least(offset + duzina)
            payload = self._buf[offset:offset + duzina]
        self._buf = self._buf[offset + duzina:]
        return fin, opcode, payload

    # ------------------------------------------------------------ utičnica

    def _read_exact(self, n):
        self._read_at_least(n)
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def _read_at_least(self, n):
        while len(self._buf) < n:
            self._napuni()

    def _read_until(self, kraj):
        while kraj not in self._buf:
            self._napuni()
        i = self._buf.index(kraj) + len(kraj)
        data, self._buf = self._buf[:i], self._buf[i:]
        return data

    def set_timeout(self, seconds):
        """Promeni koliko se ceka na sledeci bajt.

        Live API posle zvuka ne zatvara vezu — salje prazne poruke dok radi, pa
        stane. Kratak timeout je zato JEDINI znak da je zavrsio, i mora da se
        podesi tek za tu fazu; isti kratak timeout tokom slanja bi obarao vezu.
        """
        self._timeout = seconds
        if self._sock is not None:
            self._sock.settimeout(seconds)

    def _napuni(self):
        try:
            komad = self._sock.recv(65536)
        except (socket.timeout, BlockingIOError, ssl.SSLWantReadError,
                ssl.SSLWantWriteError) as exc:
            raise WebSocketTimeout("Isteklo vreme čekanja odgovora") from exc
        except OSError as exc:
            raise WebSocketError(f"Prekinuta veza: {exc}") from exc
        if not komad:
            raise WebSocketError("Veza zatvorena pre kraja poruke")
        self._buf += komad

    def close(self):
        if self._sock is None:
            return
        try:
            if not self._closed:
                self._send_frame(OP_CLOSE, struct.pack("!H", 1000))
        except (WebSocketError, OSError):
            pass
        try:
            self._sock.close()
        except OSError:
            pass
        self._sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_):
        self.close()
        return False


def encode_frame(opcode, payload, mask_key=None):
    """Klijentski okvir. Maska je obavezna po RFC-u, i uvek je 4 bajta."""
    if mask_key is None:
        mask_key = os.urandom(4)
    zaglavlje = bytearray()
    zaglavlje.append(0x80 | opcode)          # FIN = 1
    n = len(payload)
    if n < 126:
        zaglavlje.append(0x80 | n)           # MASK = 1
    elif n < 65536:
        zaglavlje.append(0x80 | 126)
        zaglavlje += struct.pack("!H", n)
    else:
        zaglavlje.append(0x80 | 127)
        zaglavlje += struct.pack("!Q", n)
    zaglavlje += mask_key
    return bytes(zaglavlje) + _mask(payload, mask_key)


def _mask(data, kljuc):
    return bytes(b ^ kljuc[i % 4] for i, b in enumerate(data))
