package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.InputStream
import java.net.SocketTimeoutException

/**
 * Okviri WebSocket-a se racunaju bit po bit, pa se i proveravaju tako.
 *
 * Isti razlog iz kog postoji `AacHeaderTest`: greska se vidi tek kao „veza
 * pukla", nikad kao izuzetak na pravom mestu.
 */
class WSockTest {

    /** Raspakuj klijentski okvir nazad u (fin, opcode, payload). */
    private fun raspakuj(okvir: ByteArray): Triple<Boolean, Int, ByteArray> {
        val fin = (okvir[0].toInt() and 0x80) != 0
        val opcode = okvir[0].toInt() and 0x0F
        val maskirano = (okvir[1].toInt() and 0x80) != 0
        assertTrue("klijent MORA da maskira", maskirano)
        var duzina = (okvir[1].toInt() and 0x7F).toLong()
        var i = 2
        if (duzina == 126L) {
            duzina = (((okvir[2].toInt() and 0xFF) shl 8) or (okvir[3].toInt() and 0xFF)).toLong()
            i = 4
        } else if (duzina == 127L) {
            duzina = 0
            for (k in 2..9) duzina = (duzina shl 8) or (okvir[k].toLong() and 0xFF)
            i = 10
        }
        val kljuc = okvir.copyOfRange(i, i + 4)
        i += 4
        return Triple(fin, opcode, WSock.mask(okvir.copyOfRange(i, i + duzina.toInt()), kljuc))
    }

    @Test
    fun kratakTekst() {
        val okvir = WSock.encodeFrame(WSock.OP_TEXT, "zdravo".toByteArray())
        val (fin, opcode, payload) = raspakuj(okvir)
        assertTrue(fin)
        assertEquals(WSock.OP_TEXT, opcode)
        assertEquals("zdravo", String(payload))
    }

    @Test
    fun maskiranjeJeSvojInverz() {
        val kljuc = byteArrayOf(1, 2, 3, 4)
        val data = ByteArray(50) { it.toByte() }
        assertTrue(WSock.mask(WSock.mask(data, kljuc), kljuc).contentEquals(data))
    }

    @Test
    fun granicaNa126Bajtova() {
        // 125 staje u sedam bita, 126 vec trazi prosireno polje duzine.
        val kratak = WSock.encodeFrame(WSock.OP_TEXT, ByteArray(125) { 'x'.code.toByte() })
        assertEquals(125, kratak[1].toInt() and 0x7F)
        val duzi = WSock.encodeFrame(WSock.OP_TEXT, ByteArray(126) { 'x'.code.toByte() })
        assertEquals(126, duzi[1].toInt() and 0x7F)
        assertEquals(126, raspakuj(duzi).third.size)
    }

    @Test
    fun granicaNa65536Bajtova() {
        val veliki = WSock.encodeFrame(WSock.OP_TEXT, ByteArray(70_000) { 'y'.code.toByte() })
        assertEquals(127, veliki[1].toInt() and 0x7F)
        assertEquals(70_000, raspakuj(veliki).third.size)
    }

    @Test
    fun prazanPayload() {
        val okvir = WSock.encodeFrame(WSock.OP_CLOSE, ByteArray(0))
        val (_, opcode, payload) = raspakuj(okvir)
        assertEquals(WSock.OP_CLOSE, opcode)
        assertEquals(0, payload.size)
    }

    @Test
    fun maskaSeMenjaIzmedjuOkvira() {
        // Ista maska na svakom okviru je poznata slabost; RFC trazi nasumicnu.
        val maske = (1..20).map {
            WSock.encodeFrame(WSock.OP_TEXT, "abc".toByteArray()).copyOfRange(2, 6).toList()
        }.toSet()
        assertTrue("maska mora da se menja", maske.size > 1)
    }

    /**
     * Vektor iz RFC 6455, odeljak 1.3.
     *
     * GUID se prekucava lako pogresno, a greska se ne vidi kao pad nego kao
     * „Pogresan Sec-WebSocket-Accept" nad savrseno ispravnim 101 odgovorom.
     * Na Mac strani je bio pogresan tacno tako i prosao je SVE ostale testove.
     */
    @Test
    fun rfcVektor() {
        assertEquals(
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
            WSock.accept("dGhlIHNhbXBsZSBub25jZQ=="),
        )
    }

    @Test
    fun guidJeTacan() {
        assertEquals("258EAFA5-E914-47DA-95CA-C5AB0DC85B11", WSock.GUID)
    }

    @Test
    fun razlicitKljucDajeRazlicitAccept() {
        assertNotEquals(WSock.accept("aaaa"), WSock.accept("bbbb"))
    }

    @Test
    fun timeoutUsredOkviraNeGubiPocetak() {
        val payload = "{\"a\":1}".toByteArray()
        val frame = byteArrayOf(0x81.toByte(), payload.size.toByte()) + payload
        val socket = WSock("ws://primer/x")
        val fake = object : InputStream() {
            var step = 0
            override fun read(): Int = -1
            override fun read(buffer: ByteArray, off: Int, len: Int): Int = when (step++) {
                0 -> {
                    frame.copyInto(buffer, off, 0, 4)
                    4
                }
                1 -> throw SocketTimeoutException()
                2 -> {
                    frame.copyInto(buffer, off, 4, frame.size)
                    frame.size - 4
                }
                else -> -1
            }
        }
        WSock::class.java.getDeclaredField("input").apply { isAccessible = true }
            .set(socket, fake)
        try {
            socket.recvText()
            throw AssertionError("Ocekivan timeout")
        } catch (_: WSock.WSTimeout) {
        }
        assertEquals("{\"a\":1}", socket.recvText())
    }
}
