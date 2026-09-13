package studio.room211.diktat

import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.net.URI
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import javax.net.ssl.SSLSocketFactory

/**
 * Najmanji moguci WebSocket klijent (RFC 6455), samo za Gemini Live API.
 *
 * Zasto rucno a ne OkHttp: aplikacija nema nijednu mreznu zavisnost — sve ide
 * preko `HttpURLConnection`, kao sto na Mac-u ide preko `urllib`. Live API nam
 * treba samo za jedan tok: posalji JSON okvire, citaj JSON okvire, zatvori.
 * Dodavati biblioteku od par stotina kilobajta zbog toga nema smisla; APK je
 * ceo 1.7 MB.
 *
 * Podrzano je tacno ono sto taj tok trazi: tekstualni okviri, nastavak okvira,
 * odgovor na ping, uredno zatvaranje. Nema kompresije ni podele slanja.
 *
 * Ovo je prevod `dictate/wsock.py` — ako se menja logika, menja se na oba mesta.
 */
class WSock(
    private val url: String,
    private var timeoutMs: Int = 30_000,
) : AutoCloseable {

    open class WSException(message: String, val retryable: Boolean = true) : Exception(message)
    class WSTimeout : WSException("Isteklo vreme cekanja odgovora")

    /** Razlog zatvaranja iz CLOSE okvira; jedini trag zasto je sesija pala. */
    var closeCode: Int? = null
        private set
    var closeReason: String = ""
        private set

    private var socket: Socket? = null
    private var input: InputStream? = null
    private var output: OutputStream? = null
    private var closed = false
    private val sendLock = Any()
    private var frameBuffer = ByteArray(0)
    private val fragments = java.io.ByteArrayOutputStream()
    private var fragmentStarted = false

    fun connect(): WSock {
        val uri = URI(url)
        val secure = when (uri.scheme) {
            "wss" -> true
            "ws" -> false
            else -> throw WSException("Nepodrzana sema: ${uri.scheme}", retryable = false)
        }
        val host = uri.host
        val port = if (uri.port > 0) uri.port else if (secure) 443 else 80
        val path = (uri.rawPath.ifEmpty { "/" }) +
            (uri.rawQuery?.let { "?$it" } ?: "")

        val sock = try {
            val plain = Socket()
            plain.connect(InetSocketAddress(host, port), timeoutMs)
            if (secure) {
                (SSLSocketFactory.getDefault() as SSLSocketFactory)
                    .createSocket(plain, host, port, true)
                    .also { (it as javax.net.ssl.SSLSocket).startHandshake() }
            } else {
                plain
            }
        } catch (e: Exception) {
            throw WSException("Ne mogu da se povezem: ${e.message}")
        }
        sock.soTimeout = timeoutMs
        socket = sock
        input = sock.getInputStream().buffered()
        output = sock.getOutputStream()

        val kljuc = Base64.getEncoder().encodeToString(ByteArray(16).also { RANDOM.nextBytes(it) })
        val zahtev = buildString {
            append("GET $path HTTP/1.1\r\n")
            append(if (port == 80 || port == 443) "Host: $host\r\n" else "Host: $host:$port\r\n")
            append("Upgrade: websocket\r\n")
            append("Connection: Upgrade\r\n")
            append("Sec-WebSocket-Key: $kljuc\r\n")
            append("Sec-WebSocket-Version: 13\r\n\r\n")
        }
        sendAll(zahtev.toByteArray(Charsets.ISO_8859_1))
        checkHandshake(kljuc)
        return this
    }

    private fun checkHandshake(kljuc: String) {
        val zaglavlje = readUntilBlankLine()
        val redovi = zaglavlje.split("\r\n")
        val prva = redovi.firstOrNull().orEmpty()
        if (!prva.contains(" 101")) {
            val kod = prva.split(" ").getOrNull(1) ?: "?"
            throw WSException(
                "Rukovanje odbijeno: ${prva.trim()}",
                retryable = kod !in setOf("400", "401", "403", "404"),
            )
        }
        val ocekivano = accept(kljuc)
        for (red in redovi.drop(1)) {
            val i = red.indexOf(':')
            if (i <= 0) continue
            if (red.substring(0, i).trim().lowercase() != "sec-websocket-accept") continue
            if (red.substring(i + 1).trim() != ocekivano) {
                throw WSException("Pogresan Sec-WebSocket-Accept", retryable = false)
            }
            return
        }
        throw WSException("Nema Sec-WebSocket-Accept u odgovoru", retryable = false)
    }

    // ------------------------------------------------------------- slanje

    fun sendText(tekst: String) = sendFrame(OP_TEXT, tekst.toByteArray(Charsets.UTF_8))

    private fun sendFrame(opcode: Int, payload: ByteArray) {
        if (socket == null) throw WSException("Veza nije otvorena", retryable = false)
        synchronized(sendLock) { sendAll(encodeFrame(opcode, payload)) }
    }

    private fun sendAll(data: ByteArray) {
        try {
            output!!.write(data)
            output!!.flush()
        } catch (e: Exception) {
            throw WSException("Slanje nije uspelo: ${e.message}")
        }
    }

    // ------------------------------------------------------------- prijem

    /** Sledeca poruka kao tekst; `null` znaci da je druga strana zatvorila. */
    fun recvText(): String? {
        while (true) {
            val (fin, opcode, payload) = recvFrame()
            when (opcode) {
                OP_CLOSE -> {
                    closed = true
                    if (payload.size >= 2) {
                        closeCode = ((payload[0].toInt() and 0xFF) shl 8) or
                            (payload[1].toInt() and 0xFF)
                        closeReason = String(payload, 2, payload.size - 2, Charsets.UTF_8)
                    }
                    return null
                }
                OP_PING -> { sendFrame(OP_PONG, payload); continue }
                OP_PONG -> continue
                OP_CONT -> if (!fragmentStarted) {
                    throw WSException("Nastavak okvira bez pocetka", retryable = false)
                }
                else -> fragmentStarted = true
            }
            fragments.write(payload)
            // Live API isti JSON ume da posalje i kao tekstualni i kao binarni
            // okvir, pa se oba dekodiraju isto.
            if (fin) {
                val text = String(fragments.toByteArray(), Charsets.UTF_8)
                fragments.reset()
                fragmentStarted = false
                return text
            }
        }
    }

    private fun recvFrame(): Triple<Boolean, Int, ByteArray> {
        // Kratak timeout može pasti usred okvira. Bajtove trošimo tek kada
        // stigne ceo okvir, da sledeće čitanje nastavi na pravom mestu.
        readFrameBytes(2)
        val fin = (frameBuffer[0].toInt() and 0x80) != 0
        val opcode = frameBuffer[0].toInt() and 0x0F
        val maskirano = (frameBuffer[1].toInt() and 0x80) != 0
        var duzina = (frameBuffer[1].toInt() and 0x7F).toLong()
        var offset = 2
        if (duzina == 126L) {
            readFrameBytes(offset + 2)
            duzina = (((frameBuffer[offset].toInt() and 0xFF) shl 8) or
                (frameBuffer[offset + 1].toInt() and 0xFF)).toLong()
            offset += 2
        } else if (duzina == 127L) {
            readFrameBytes(offset + 8)
            duzina = 0
            for (i in offset until offset + 8) {
                duzina = (duzina shl 8) or (frameBuffer[i].toLong() and 0xFF)
            }
            offset += 8
        }
        if (duzina > MAX_FRAME) throw WSException("Okvir je prevelik: $duzina", retryable = false)
        val maskOffset = if (maskirano) 4 else 0
        readFrameBytes(offset + maskOffset + duzina.toInt())
        // Server nikad ne maskira; ako maskira, protokol je prekrsen.
        val payload = if (maskirano) {
            val key = frameBuffer.copyOfRange(offset, offset + 4)
            mask(frameBuffer.copyOfRange(offset + 4, offset + 4 + duzina.toInt()), key)
        } else {
            frameBuffer.copyOfRange(offset, offset + duzina.toInt())
        }
        frameBuffer = frameBuffer.copyOfRange(offset + maskOffset + duzina.toInt(), frameBuffer.size)
        return Triple(fin, opcode, payload)
    }

    private fun readFrameBytes(n: Int) {
        while (frameBuffer.size < n) {
            val chunk = ByteArray(maxOf(4096, n - frameBuffer.size))
            val count = try {
                input!!.read(chunk)
            } catch (e: SocketTimeoutException) {
                throw WSTimeout()
            } catch (e: Exception) {
                throw WSException("Prekinuta veza: ${e.message}")
            }
            if (count < 0) throw WSException("Veza zatvorena pre kraja poruke")
            if (count > 0) frameBuffer += chunk.copyOf(count)
        }
    }

    /**
     * Promeni koliko se ceka na sledeci bajt.
     *
     * Live API posle zvuka ne zatvara vezu — salje prazne poruke dok radi, pa
     * stane. Kratak timeout je zato JEDINI znak da je zavrsio, i mora da se
     * podesi tek za tu fazu; isti kratak timeout tokom slanja bi obarao vezu.
     */
    fun setTimeout(ms: Int) {
        timeoutMs = ms
        socket?.soTimeout = ms
    }

    // ------------------------------------------------------------- uticnica

    private fun readExact(n: Int): ByteArray {
        val out = ByteArray(n)
        var procitano = 0
        while (procitano < n) {
            val k = try {
                input!!.read(out, procitano, n - procitano)
            } catch (e: SocketTimeoutException) {
                throw WSException("Isteklo vreme cekanja odgovora")
            } catch (e: Exception) {
                throw WSException("Prekinuta veza: ${e.message}")
            }
            if (k < 0) throw WSException("Veza zatvorena pre kraja poruke")
            procitano += k
        }
        return out
    }

    private fun readUntilBlankLine(): String {
        val buf = java.io.ByteArrayOutputStream()
        var uzastopnih = 0
        while (uzastopnih < 4) {
            val b = readExact(1)[0]
            buf.write(b.toInt())
            val ocekivan = when (uzastopnih) { 0, 2 -> '\r'.code.toByte(); else -> '\n'.code.toByte() }
            uzastopnih = if (b == ocekivan) uzastopnih + 1 else if (b == '\r'.code.toByte()) 1 else 0
        }
        return String(buf.toByteArray(), Charsets.ISO_8859_1)
    }

    override fun close() {
        val sock = socket ?: return
        try {
            if (!closed) sendFrame(OP_CLOSE, byteArrayOf(0x03, 0xE8.toByte()))  // 1000
        } catch (_: Exception) {
        }
        try { sock.close() } catch (_: Exception) {}
        socket = null
    }

    companion object {
        /**
         * Fiksna konstanta iz RFC 6455; sluzi samo za proveru odgovora.
         *
         * Prekucava se lako pogresno (poslednje dve grupe), a greska se vidi
         * tek kao „Pogresan Sec-WebSocket-Accept" nad ispravnim 101 odgovorom —
         * zato test nad vektorom iz samog RFC-a, ne nad nasumicnim kljucem.
         */
        const val GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

        const val OP_CONT = 0x0
        const val OP_TEXT = 0x1
        const val OP_BINARY = 0x2
        const val OP_CLOSE = 0x8
        const val OP_PING = 0x9
        const val OP_PONG = 0xA

        private const val MAX_FRAME = 16L * 1024 * 1024
        private val RANDOM = SecureRandom()

        fun accept(kljuc: String): String {
            val sha = MessageDigest.getInstance("SHA-1")
                .digest((kljuc + GUID).toByteArray(Charsets.US_ASCII))
            return Base64.getEncoder().encodeToString(sha)
        }

        /** Klijentski okvir. Maska je obavezna po RFC-u, i uvek je 4 bajta. */
        fun encodeFrame(opcode: Int, payload: ByteArray, maskKey: ByteArray? = null): ByteArray {
            val kljuc = maskKey ?: ByteArray(4).also { RANDOM.nextBytes(it) }
            val out = java.io.ByteArrayOutputStream()
            out.write(0x80 or opcode)                       // FIN = 1
            val n = payload.size
            when {
                n < 126 -> out.write(0x80 or n)             // MASK = 1
                n < 65536 -> {
                    out.write(0x80 or 126)
                    out.write((n shr 8) and 0xFF); out.write(n and 0xFF)
                }
                else -> {
                    out.write(0x80 or 127)
                    for (i in 7 downTo 0) out.write((n shr (8 * i)) and 0xFF)
                }
            }
            out.write(kljuc)
            out.write(mask(payload, kljuc))
            return out.toByteArray()
        }

        fun mask(data: ByteArray, kljuc: ByteArray): ByteArray {
            val out = ByteArray(data.size)
            for (i in data.indices) out[i] = (data[i].toInt() xor kljuc[i % 4].toInt()).toByte()
            return out
        }
    }
}
