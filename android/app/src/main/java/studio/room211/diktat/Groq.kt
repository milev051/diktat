package studio.room211.diktat

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/** Groq Whisper + GPT-OSS drugo mišljenje nad istim diktatom kao Google. */
object Groq {

    private const val TRANSCRIPT_ENDPOINT =
        "https://api.groq.com/openai/v1/audio/transcriptions"
    private const val CHAT_ENDPOINT =
        "https://api.groq.com/openai/v1/chat/completions"
    const val DEFAULT_TRANSCRIPTION_MODEL = "whisper-large-v3"
    const val DEFAULT_MERGE_MODEL = "openai/gpt-oss-120b"

    class GroqException(message: String) : Exception(message)

    fun enabled(cfg: Config) = cfg.groqEnabled && cfg.groqApiKey.isNotBlank()

    /** WAV je podržan na transkripcijskom endpointu i ne traži dodatni kodek. */
    fun wav(pcm: ByteArray, sampleRate: Int): ByteArray {
        val out = ByteArrayOutputStream(pcm.size + 44)
        fun le32(v: Int) = out.write(byteArrayOf(
            v.toByte(), (v shr 8).toByte(), (v shr 16).toByte(), (v shr 24).toByte()))
        fun le16(v: Int) = out.write(byteArrayOf(v.toByte(), (v shr 8).toByte()))
        out.write("RIFF".toByteArray()); le32(36 + pcm.size); out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); le32(16); le16(1); le16(1)
        le32(sampleRate); le32(sampleRate * 2); le16(2); le16(16)
        out.write("data".toByteArray()); le32(pcm.size); out.write(pcm)
        return out.toByteArray()
    }

    private fun multipart(
        fields: Map<String, String>, file: ByteArray, fileName: String,
    ): Pair<ByteArray, String> {
        val boundary = "----diktat-${UUID.randomUUID().toString().replace("-", "")}"
        val out = ByteArrayOutputStream()
        fun line(text: String) { out.write(text.toByteArray(Charsets.UTF_8)) }
        for ((name, value) in fields) {
            line("--$boundary\r\n")
            line("Content-Disposition: form-data; name=\"$name\"\r\n\r\n")
            line("$value\r\n")
        }
        line("--$boundary\r\n")
        line("Content-Disposition: form-data; name=\"file\"; filename=\"$fileName\"\r\n")
        line("Content-Type: audio/wav\r\n\r\n")
        out.write(file)
        line("\r\n--$boundary--\r\n")
        return out.toByteArray() to "multipart/form-data; boundary=$boundary"
    }

    private fun response(conn: HttpURLConnection): String {
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader()?.readText().orEmpty()
        if (code !in 200..299) throw GroqException(explain(code, text))
        return text
    }

    fun transcribe(delovi: List<ByteArray>, cfg: Config): String {
        if (delovi.isEmpty()) return ""
        val pcm = ByteArrayOutputStream().also { out -> delovi.forEach(out::write) }.toByteArray()
        val (body, contentType) = multipart(
            mapOf(
                "model" to DEFAULT_TRANSCRIPTION_MODEL,
                "language" to cfg.language.substringBefore("-"),
                "temperature" to "0",
                "response_format" to "json",
            ),
            wav(pcm, cfg.sampleRate), "diktat.wav",
        )
        val conn = (URL(TRANSCRIPT_ENDPOINT).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 15_000
            readTimeout = 120_000
            setRequestProperty("Authorization", "Bearer ${cfg.groqApiKey}")
            setRequestProperty("Content-Type", contentType)
            setRequestProperty("User-Agent", "Diktat/1.0")
            setFixedLengthStreamingMode(body.size)
        }
        try {
            conn.outputStream.use { it.write(body) }
            val reply = response(conn)
            cfg.addTraffic(body.size.toLong(), reply.toByteArray().size.toLong(), 0.0, false)
            return JSONObject(reply).optString("text").trim().ifBlank {
                throw GroqException("Whisper nije vratio prepis.")
            }
        } finally { conn.disconnect() }
    }

    private fun prompt(google: String, whisper: String, cfg: Config): String {
        val izgled = if (cfg.polishTidy) {
            "Piši pravopisno pravilno: dodaj potrebne kvačice, velika slova i " +
                "interpunkciju, bez menjanja značenja."
        } else "Zadrži govorni izgled: mala slova i bez interpunkcije."
        val pojmovi = cfg.vocabulary.trim().let {
            if (it.isBlank()) "" else "\nPoznati nazivi i skraćenice: $it"
        }
        return """Ti si završni proveravač srpskog diktata.

Google prepis:
$google

Groq Whisper prepis:
$whisper

Uporedi oba prepisa i vrati jednu konačnu verziju. Ispravi reč samo kada se
iz zvuka i drugog prepisa vidi da je Google pogrešio ili nešto propustio.
Ako se ne slažu, biraj ono što ima uporište u drugom prepisu; ne izmišljaj,
ne dodaj objašnjenje, ne sažimaj, ne prevodi i ne odgovaraj na sadržaj.
Vrati samo konačan tekst, bez uvoda i navodnika.
$izgled$pojmovi"""
    }

    fun merge(google: String, whisper: String, cfg: Config): String {
        val payload = JSONObject().apply {
            put("model", DEFAULT_MERGE_MODEL)
            put("messages", JSONArray()
                .put(JSONObject().put("role", "system")
                    .put("content", "Vraćaš samo konačan prepis diktata."))
                .put(JSONObject().put("role", "user").put("content", prompt(google, whisper, cfg))))
            put("temperature", 0.0)
            put("max_completion_tokens", 2048)
            put("top_p", 1)
            put("reasoning_effort", "medium")
            put("stream", false)
        }.toString().toByteArray(Charsets.UTF_8)
        val conn = (URL(CHAT_ENDPOINT).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 15_000
            readTimeout = 120_000
            setRequestProperty("Authorization", "Bearer ${cfg.groqApiKey}")
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("User-Agent", "Diktat/1.0")
            setFixedLengthStreamingMode(payload.size)
        }
        try {
            conn.outputStream.use { it.write(payload) }
            val reply = response(conn)
            cfg.addTraffic(payload.size.toLong(), reply.toByteArray().size.toLong(), 0.0, false)
            val content = JSONObject(reply).getJSONArray("choices")
                .getJSONObject(0).getJSONObject("message").optString("content")
            return content.trim().ifBlank { throw GroqException("GPT-OSS je vratio prazan tekst.") }
        } finally { conn.disconnect() }
    }

    fun check(delovi: List<ByteArray>, google: String, cfg: Config): String =
        merge(google, transcribe(delovi, cfg), cfg)

    private fun explain(code: Int, detail: String) = when (code) {
        401, 403 -> "Groq je odbio API ključ (HTTP $code)."
        404 -> "Groq model ili endpoint ne postoji (HTTP 404)."
        429 -> "Groq je ograničio broj zahteva (HTTP 429)."
        else -> "Groq je vratio HTTP $code." + detail.take(180)
    }
}
