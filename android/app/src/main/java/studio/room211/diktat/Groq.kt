package studio.room211.diktat

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Groq GPT-OSS obrada već transkribovanog teksta. */
object Groq {

    private const val CHAT_ENDPOINT =
        "https://api.groq.com/openai/v1/chat/completions"
    const val DEFAULT_TEXT_MODEL = "openai/gpt-oss-120b"

    class GroqException(message: String) : Exception(message)

    private fun response(conn: HttpURLConnection): String {
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader()?.readText().orEmpty()
        if (code !in 200..299) throw GroqException(explain(code, text))
        return text
    }

    /** Provera autentifikacije bez slanja audio-snimka ili teksta. */
    fun testKey(cfg: Config): String {
        if (cfg.groqApiKey.isBlank()) throw GroqException("Groq API ključ nije podešen.")
        val conn = (URL("https://api.groq.com/openai/v1/models").openConnection()
            as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15_000
            readTimeout = 30_000
            setRequestProperty("Authorization", "Bearer ${cfg.groqApiKey}")
            setRequestProperty("User-Agent", "Diktat/1.0")
        }
        return try {
            val reply = response(conn)
            val count = runCatching { JSONObject(reply).optJSONArray("data")?.length() ?: 0 }
                .getOrDefault(0)
            "Groq ključ radi ($count modela dostupno)"
        } finally {
            conn.disconnect()
        }
    }

    /** Obradi tekst bez slanja audio-snimka. */
    fun manipulateText(text: String, instruction: String, cfg: Config): String {
        val payload = JSONObject().apply {
            put("model", DEFAULT_TEXT_MODEL)
            put("messages", JSONArray()
                .put(JSONObject().put("role", "system")
                    .put("content", "Poštuj uputstvo i vrati samo konačan obrađen tekst."))
                .put(JSONObject().put("role", "user")
                    .put("content", "$instruction\n\nSirov transkript:\n$text")))
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
            readTimeout = 60_000
            setRequestProperty("Authorization", "Bearer ${cfg.groqApiKey}")
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("User-Agent", "Diktat/1.0")
            setFixedLengthStreamingMode(payload.size)
        }
        try {
            conn.outputStream.use { it.write(payload) }
            val reply = response(conn)
            cfg.addTraffic(
                payload.size.toLong(), reply.toByteArray().size.toLong(), 0.0, false,
            )
            val content = JSONObject(reply).getJSONArray("choices")
                .getJSONObject(0).getJSONObject("message").optString("content")
            return content.trim().ifBlank {
                throw GroqException("GPT-OSS je vratio prazan tekst za obradu.")
            }
        } finally { conn.disconnect() }
    }

    private fun explain(code: Int, detail: String) = when (code) {
        401, 403 -> "Groq je odbio API ključ (HTTP $code)."
        404 -> "Groq model ili endpoint ne postoji (HTTP 404)."
        429 -> "Groq je ograničio broj zahteva (HTTP 429)."
        else -> "Groq je vratio HTTP $code." + detail.take(180)
    }
}
