"""Okviri WebSocket-a se racunaju rukom, pa se i proveravaju rukom.

Ista logika kao kod ADTS zaglavlja na Androidu: sve sto se sklapa bit po bit
mora da ima test, jer se greska vidi tek kao "veza pukla" i nikad kao izuzetak
na pravom mestu.
"""

import struct
import unittest

from dictate import wsock


def raspakuj(okvir):
    """Vrati (fin, opcode, payload) iz klijentskog okvira."""
    fin = bool(okvir[0] & 0x80)
    opcode = okvir[0] & 0x0F
    maskirano = bool(okvir[1] & 0x80)
    duzina = okvir[1] & 0x7F
    i = 2
    if duzina == 126:
        duzina = struct.unpack("!H", okvir[i:i + 2])[0]
        i += 2
    elif duzina == 127:
        duzina = struct.unpack("!Q", okvir[i:i + 8])[0]
        i += 8
    assert maskirano, "klijent MORA da maskira"
    kljuc = okvir[i:i + 4]
    i += 4
    return fin, opcode, wsock._mask(okvir[i:i + duzina], kljuc)


class Okviri(unittest.TestCase):
    def test_kratak_tekst(self):
        okvir = wsock.encode_frame(wsock.OP_TEXT, b"zdravo")
        self.assertEqual(raspakuj(okvir), (True, wsock.OP_TEXT, b"zdravo"))

    def test_klijent_uvek_maskira(self):
        okvir = wsock.encode_frame(wsock.OP_TEXT, b"a")
        self.assertTrue(okvir[1] & 0x80, "MASK bit mora da stoji")

    def test_maskiranje_je_svoj_inverz(self):
        kljuc = b"\x01\x02\x03\x04"
        data = bytes(range(50))
        self.assertEqual(wsock._mask(wsock._mask(data, kljuc), kljuc), data)

    def test_granica_na_126_bajtova(self):
        # 125 staje u sedam bita, 126 vec trazi prosireno polje duzine.
        kratak = wsock.encode_frame(wsock.OP_TEXT, b"x" * 125)
        self.assertEqual(kratak[1] & 0x7F, 125)
        duzi = wsock.encode_frame(wsock.OP_TEXT, b"x" * 126)
        self.assertEqual(duzi[1] & 0x7F, 126)
        self.assertEqual(raspakuj(duzi)[2], b"x" * 126)

    def test_granica_na_65536_bajtova(self):
        veliki = wsock.encode_frame(wsock.OP_TEXT, b"y" * 70000)
        self.assertEqual(veliki[1] & 0x7F, 127)
        self.assertEqual(raspakuj(veliki)[2], b"y" * 70000)

    def test_prazan_payload(self):
        okvir = wsock.encode_frame(wsock.OP_CLOSE, b"")
        self.assertEqual(raspakuj(okvir), (True, wsock.OP_CLOSE, b""))

    def test_maska_se_menja_izmedju_okvira(self):
        # Ista maska na svakom okviru je poznata slabost; RFC trazi nasumicnu.
        maske = {wsock.encode_frame(wsock.OP_TEXT, b"abc")[2:6] for _ in range(20)}
        self.assertGreater(len(maske), 1)


class LazniSokat:
    """Vraca unapred pripremljene bajtove, u komadima kao prava utičnica."""

    def __init__(self, data, korak=7):
        self._data = data
        self._korak = korak
        self.poslato = b""

    def recv(self, _n):
        komad, self._data = self._data[:self._korak], self._data[self._korak:]
        return komad

    def sendall(self, data):
        self.poslato += data

    def close(self):
        pass


def server_okvir(opcode, payload, fin=True):
    """Server ne maskira, pa je okvir prostiji od klijentskog."""
    zaglavlje = bytearray([(0x80 if fin else 0) | opcode])
    n = len(payload)
    if n < 126:
        zaglavlje.append(n)
    elif n < 65536:
        zaglavlje.append(126)
        zaglavlje += struct.pack("!H", n)
    else:
        zaglavlje.append(127)
        zaglavlje += struct.pack("!Q", n)
    return bytes(zaglavlje) + payload


def napravi(data):
    ws = wsock.WebSocket("wss://primer/x")
    ws._sock = LazniSokat(data)
    return ws


class Citanje(unittest.TestCase):
    def test_jedna_poruka(self):
        ws = napravi(server_okvir(wsock.OP_TEXT, b'{"a":1}'))
        self.assertEqual(ws.recv_json(), {"a": 1})

    def test_poruka_iz_vise_okvira(self):
        data = (
            server_okvir(wsock.OP_TEXT, b'{"a":', fin=False)
            + server_okvir(wsock.OP_CONT, b'1}', fin=True)
        )
        self.assertEqual(napravi(data).recv_json(), {"a": 1})

    def test_ping_se_odgovara_pa_se_cita_dalje(self):
        data = (
            server_okvir(wsock.OP_PING, b"ping")
            + server_okvir(wsock.OP_TEXT, b'{"b":2}')
        )
        ws = napravi(data)
        self.assertEqual(ws.recv_json(), {"b": 2})
        _, opcode, payload = raspakuj(ws._sock.poslato)
        self.assertEqual((opcode, payload), (wsock.OP_PONG, b"ping"))

    def test_zatvaranje_vraca_none(self):
        self.assertIsNone(napravi(server_okvir(wsock.OP_CLOSE, b"")).recv_json())

    def test_binarni_okvir_se_cita_kao_json(self):
        # Live API isti JSON ume da posalje i kao binarni okvir.
        ws = napravi(server_okvir(wsock.OP_BINARY, b'{"c":3}'))
        self.assertEqual(ws.recv_json(), {"c": 3})

    def test_prekinuta_veza_usred_poruke(self):
        ws = napravi(server_okvir(wsock.OP_TEXT, b"12345")[:4])
        with self.assertRaises(wsock.WebSocketError):
            ws.recv_json()



class Rukovanje(unittest.TestCase):
    """Vektor iz RFC 6455, odeljak 1.3.

    GUID se prekucava lako pogrešno, a greška se ne vidi kao pad nego kao
    „Pogrešan Sec-WebSocket-Accept" nad savršeno ispravnim 101 odgovorom.
    Prvi put je bio pogrešan tačno tako i prošao je sve ostale testove.
    """

    KLJUC = "dGhlIHNhbXBsZSBub25jZQ=="
    ACCEPT = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="

    def accept(self, kljuc):
        import base64, hashlib
        return base64.b64encode(
            hashlib.sha1((kljuc + wsock.GUID).encode("ascii")).digest()
        ).decode("ascii")

    def test_rfc_vektor(self):
        self.assertEqual(self.accept(self.KLJUC), self.ACCEPT)

    def test_ispravan_accept_prolazi(self):
        ws = napravi(b"")
        odgovor = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {self.ACCEPT}\r\n\r\n"
        ).encode()
        ws._sock = LazniSokat(odgovor)
        ws._check_handshake(self.KLJUC)          # ne sme da pukne

    def test_pogresan_accept_pada(self):
        ws = napravi(b"")
        odgovor = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Sec-WebSocket-Accept: niiiisam=\r\n\r\n"
        ).encode()
        ws._sock = LazniSokat(odgovor)
        with self.assertRaises(wsock.WebSocketError):
            ws._check_handshake(self.KLJUC)

    def test_odbijeno_rukovanje_ne_ponavlja_se_na_403(self):
        ws = napravi(b"")
        ws._sock = LazniSokat(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        with self.assertRaises(wsock.WebSocketError) as ctx:
            ws._check_handshake(self.KLJUC)
        self.assertFalse(ctx.exception.retryable)

    def test_prolazna_greska_servera_se_ponavlja(self):
        ws = napravi(b"")
        ws._sock = LazniSokat(b"HTTP/1.1 503 Service Unavailable\r\n\r\n")
        with self.assertRaises(wsock.WebSocketError) as ctx:
            ws._check_handshake(self.KLJUC)
        self.assertTrue(ctx.exception.retryable)

if __name__ == "__main__":
    unittest.main()
