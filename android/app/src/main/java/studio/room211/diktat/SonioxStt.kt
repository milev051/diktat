package studio.room211.diktat

import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread

/**
 * Soniox `stt-rt-v6` uživo, preko WebSocket-a. Prevod `dictate/sonioxstt.py`;
 * ako se logika menja, menja se na oba mesta.
 *
 * Prva poruka je JSON podešavanje (sa ključem), pa binarni PCM komadi, a
 * prazna poruka označava kraj zvuka. Server vraća `tokens` i na kraju
 * `finished: true`. Ključ korisnik upisuje u aplikaciji.
 */
object SonioxStt {
    class SonioxException(message: String, val retryable: Boolean = true) : Exception(message)

    const val WS_ENDPOINT = "wss://stt-rt.soniox.com/transcribe-websocket"
    const val MODEL = "stt-rt-v6"
    private const val KRAJ_ROK_MS = 15_000L

    fun enabled(cfg: Config): Boolean = cfg.transcriptionProvider == "soniox"

    fun setup(key: String, rate: Int): JSONObject = JSONObject()
        .put("api_key", key)
        .put("model", MODEL)
        .put("audio_format", "pcm_s16le")
        .put("sample_rate", rate)
        .put("num_channels", 1)
        .put("language_hints", JSONArray().put("sr"))

    /** Tekst tokena bez kontrolnih (<end>, <fin>). */
    fun tekst(tokeni: List<JSONObject>): String =
        tokeni.map { it.optString("text") }.filterNot { it.startsWith("<") }.joinToString("")

    fun recognizeStream(
        cfg: Config,
        onUpdate: ((String) -> Unit)? = null,
        veza: AtomicReference<WSock?>? = null,
        komadi: () -> ByteArray?,
    ): String {
        val key = cfg.sonioxApiKey.trim()
        if (key.isEmpty()) throw SonioxException("Soniox API ključ nije podešen", retryable = false)
        val konacni = mutableListOf<JSONObject>()
        var privremeni = listOf<JSONObject>()
        val poslato = AtomicBoolean(false)
        val kraj = AtomicBoolean(false)
        val greska = AtomicReference<Exception?>(null)

        WSock(WS_ENDPOINT, 20_000).use { ws ->
            veza?.set(ws)
            try {
                ws.connect()
                ws.sendText(setup(key, cfg.sampleRate).toString())
                ws.setTimeout(500)
                val citac = thread(name = "soniox-citac") {
                    var rok = 0L
                    try {
                        while (true) {
                            if (poslato.get() && rok == 0L) rok = System.currentTimeMillis() + KRAJ_ROK_MS
                            if (rok != 0L && System.currentTimeMillis() > rok) break
                            val poruka = try {
                                ws.recvText()
                            } catch (_: WSock.WSTimeout) {
                                continue
                            } ?: break
                            val o = JSONObject(poruka)
                            if (o.has("error_code") || o.has("error_message")) {
                                val kod = o.optInt("error_code")
                                throw SonioxException(
                                    "Soniox $kod: ${o.optString("error_message").take(200)}",
                                    retryable = kod !in setOf(400, 401, 402, 403),
                                )
                            }
                            val niz = o.optJSONArray("tokens")
                            if (niz != null && niz.length() > 0) {
                                val tokeni = (0 until niz.length()).map { niz.getJSONObject(it) }
                                synchronized(konacni) {
                                    konacni += tokeni.filter { it.optBoolean("is_final") }
                                    privremeni = tokeni.filterNot { it.optBoolean("is_final") }
                                }
                                val prikaz = synchronized(konacni) { tekst(konacni) + tekst(privremeni) }
                                if (onUpdate != null) runCatching { onUpdate(prikaz.trim()) }
                            }
                            if (o.optBoolean("finished")) { kraj.set(true); break }
                        }
                    } catch (e: Exception) {
                        greska.set(e)
                    }
                }
                try {
                    while (greska.get() == null) {
                        val komad = komadi() ?: break
                        if (komad.isNotEmpty()) ws.sendBinary(komad)
                    }
                    if (greska.get() == null) ws.sendText("")
                } finally {
                    poslato.set(true)
                }
                citac.join(KRAJ_ROK_MS + 2_000)
            } catch (e: WSock.WSException) {
                throw SonioxException("Soniox: ${e.message}", e.retryable)
            } finally {
                veza?.set(null)
            }
        }
        greska.get()?.let {
            if (it is SonioxException) throw it
            throw SonioxException("Soniox: ${it.message}")
        }
        return synchronized(konacni) {
            (tekst(konacni) + if (kraj.get()) "" else tekst(privremeni)).trim()
        }
    }

    /** Ceo snimak odjednom (sistemski servis za prepoznavanje, tastatura). */
    fun recognize(pcm: ByteArray, cfg: Config): String {
        var i = 0
        val korak = 3200
        return recognizeStream(cfg) {
            if (i >= pcm.size) null else pcm.copyOfRange(i, minOf(pcm.size, i + korak)).also { i += korak }
        }
    }
}
