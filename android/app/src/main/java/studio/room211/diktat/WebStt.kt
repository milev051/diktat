package studio.room211.diktat

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Besplatni Google Web Speech endpoint — onaj koji koristi Chromium.
 *
 * Bez naloga i bez kredencijala. Isti onaj koji zove macOS verzija.
 *
 *   * Bez `pFilter=0` Google maskira psovke zvezdicama ("sranje" -> "s*****").
 *     Ime parametra je osetljivo na velika slova — `pfilter` se ignorise.
 *   * Odgovor je vise JSON linija; prva je obicno prazna {"result":[]}.
 *   * Prakticno ide do ~30s zvuka po zahtevu.
 */
object WebStt {

    private const val ENDPOINT = "https://www.google.com/speech-api/v2/recognize"
    private const val DEFAULT_KEY = "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"

    class SttException(message: String) : Exception(message)

    /**
     * Prvo se proba FLAC (oko 40% manje podataka), pa PCM ako ne prodje.
     * Usteda ne sme da obori diktat, pa je povratak automatski.
     */
    fun recognize(pcm: ByteArray, cfg: Config): String {
        if (pcm.isEmpty()) return ""

        if (cfg.compressAudio) {
            val flac = FlacEncoder.encode(pcm, cfg.sampleRate)
            if (flac != null) {
                runCatching { return send(flac, "audio/x-flac; rate=${cfg.sampleRate}", cfg, pcm.size) }
            }
        }
        return send(pcm, "audio/l16; rate=${cfg.sampleRate}", cfg, pcm.size)
    }

    private fun send(body: ByteArray, contentType: String, cfg: Config, pcmSize: Int): String {

        val url = URL(
            "$ENDPOINT?client=chromium" +
                "&lang=${URLEncoder.encode(cfg.language, "UTF-8")}" +
                "&key=${cfg.apiKey.ifBlank { DEFAULT_KEY }}" +
                "&pFilter=${if (cfg.profanityFilter) 1 else 0}"
        )

        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 15_000
            readTimeout = 40_000
            setRequestProperty("Content-Type", contentType)
            setFixedLengthStreamingMode(body.size)
        }

        try {
            conn.outputStream.use { it.write(body) }
            val code = conn.responseCode
            if (code != 200) throw SttException(explain(code))
            val reply = conn.inputStream.bufferedReader().readText()
            // Zvuk je daleko najveci deo; odgovor je par stotina bajtova.
            cfg.addTraffic(
                sent = body.size.toLong(),
                received = reply.toByteArray().size.toLong(),
                seconds = pcmSize / 2.0 / cfg.sampleRate,
            )
            return parse(reply)
        } finally {
            conn.disconnect()
        }
    }

    private fun parse(body: String): String {
        var best = ""
        var bestConf = -1.0
        for (line in body.lineSequence()) {
            if (line.isBlank()) continue
            val results = runCatching { JSONObject(line).optJSONArray("result") }.getOrNull()
                ?: continue
            for (i in 0 until results.length()) {
                val alts = results.getJSONObject(i).optJSONArray("alternative") ?: continue
                for (j in 0 until alts.length()) {
                    val alt = alts.getJSONObject(j)
                    val text = alt.optString("transcript").trim()
                    val conf = alt.optDouble("confidence", 0.0)
                    if (text.isNotEmpty() && conf >= bestConf) {
                        best = text
                        bestConf = conf
                    }
                }
            }
        }
        return best
    }

    private fun explain(code: Int) = when (code) {
        403 -> "Google je odbio ključ (403) — endpoint je verovatno stegnut."
        400 -> "Neispravan zahtev (400) — proveri jezik i sample rate."
        429 -> "Previše zahteva (429). Sačekaj malo."
        else -> "Google je vratio HTTP $code."
    }
}
