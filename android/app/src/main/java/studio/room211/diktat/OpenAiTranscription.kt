package studio.room211.diktat

import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException
import java.util.UUID

/**
 * Zavrsena audio-transkripcija preko OpenAI Audio Transcriptions API-ja.
 *
 * Ovo je namerno odvojeno od WebStt-a: izbor OpenAI-ja nikad ne salje isti
 * snimak Google-u, niti koristi realtime Voice/WebSocket tok.
 */
object OpenAiTranscription {

    const val ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
    const val MODEL = "gpt-transcribe"
    const val MAX_FILE_BYTES = 25 * 1024 * 1024
    private const val MODELS_ENDPOINT = "https://api.openai.com/v1/models"

    private const val RETRY_WAIT_MS = 1_000L
    private const val MAX_RETRIES = 5
    private const val MIN_AUDIO_BYTES = 6_400 // 0.2 s na 16 kHz, 16-bit mono

    class OpenAiException(message: String, val retryable: Boolean = false) : Exception(message)

    /** Provera autentifikacije bez slanja audio-snimka i bez transkripcionog poziva. */
    fun testKey(cfg: Config): String {
        val key = cfg.openAiApiKey.trim()
        if (key.isBlank()) throw OpenAiException("OpenAI API ključ nije podešen.")
        val conn = (URL(MODELS_ENDPOINT).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15_000
            readTimeout = 30_000
            setRequestProperty("Authorization", "Bearer $key")
            setRequestProperty("User-Agent", "Diktat/1.0")
        }
        return try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val reply = stream?.bufferedReader()?.readText().orEmpty()
            if (code !in 200..299) throw OpenAiException(explain(code, reply))
            val count = runCatching { JSONObject(reply).optJSONArray("data")?.length() ?: 0 }
                .getOrDefault(0)
            "OpenAI ključ radi ($count modela dostupno)"
        } finally {
            conn.disconnect()
        }
    }

    private data class EncodedAudio(
        val bytes: ByteArray,
        val fileName: String,
        val contentType: String,
    )

    private const val BASE_PROMPT =
        "Transkribuj govor na srpskom jeziku. Koristi prirodnu interpunkciju, " +
            "pravilno razdvajaj rečenice i sačuvaj značenje onoga što je izgovoreno. " +
            "Nemoj prepravljati sadržaj niti dodavati informacije koje nisu izgovorene."

    private const val CYRILLIC_PROMPT =
        " Transkribuj srpski tekst ćirilicom."

    private const val LATIN_PROMPT =
        " Transkribuj srpski tekst latinicom."

    fun prompt(script: String): String = when (script) {
        "cyrillic" -> BASE_PROMPT + CYRILLIC_PROMPT
        "latin" -> BASE_PROMPT + LATIN_PROMPT
        else -> BASE_PROMPT
    }

    /**
     * Posle modela radi samo bezbedne, lokalne izmene. Posebno, cyrillic ->
     * latin je deterministicki i ne dira URL-ove, engleske reci, brojeve,
     * razmake, interpunkciju ni prelome redova.
     */
    fun postProcess(text: String, cfg: Config): String {
        var out = when (cfg.openAiOutputScript) {
            "latin" -> toLatin(text)
            // Za cirilicu se oslanjamo na eksplicitno uputstvo modelu. Latinica
            // nema pouzdanu lokalnu oznaku kojom bi se razlikovala od engleskih
            // naziva, URL-ova i imena bez gresaka u oba smera.
            else -> text
        }.trim()
        if (out.isNotEmpty()) out = TextPolish.applyBlocks(out, cfg)
        return if (out.isNotEmpty() && cfg.trailingSpace) "$out " else out
    }

    /** Српска ћирилица -> српска латиница, знак по знак. */
    fun toLatin(text: String): String = buildString(text.length) {
        for (ch in text) append(
            when (ch) {
                'А' -> "A"; 'Б' -> "B"; 'В' -> "V"; 'Г' -> "G"; 'Д' -> "D"
                'Ђ' -> "Đ"; 'Е' -> "E"; 'Ж' -> "Ž"; 'З' -> "Z"; 'И' -> "I"
                'Ј' -> "J"; 'К' -> "K"; 'Л' -> "L"; 'Љ' -> "Lj"; 'М' -> "M"
                'Н' -> "N"; 'Њ' -> "Nj"; 'О' -> "O"; 'П' -> "P"; 'Р' -> "R"
                'С' -> "S"; 'Т' -> "T"; 'Ћ' -> "Ć"; 'У' -> "U"; 'Ф' -> "F"
                'Х' -> "H"; 'Ц' -> "C"; 'Ч' -> "Č"; 'Џ' -> "Dž"; 'Ш' -> "Š"
                'а' -> "a"; 'б' -> "b"; 'в' -> "v"; 'г' -> "g"; 'д' -> "d"
                'ђ' -> "đ"; 'е' -> "e"; 'ж' -> "ž"; 'з' -> "z"; 'и' -> "i"
                'ј' -> "j"; 'к' -> "k"; 'л' -> "l"; 'љ' -> "lj"; 'м' -> "m"
                'н' -> "n"; 'њ' -> "nj"; 'о' -> "o"; 'п' -> "p"; 'р' -> "r"
                'с' -> "s"; 'т' -> "t"; 'ћ' -> "ć"; 'у' -> "u"; 'ф' -> "f"
                'х' -> "h"; 'ц' -> "c"; 'ч' -> "č"; 'џ' -> "dž"; 'ш' -> "š"
                else -> ch.toString()
            },
        )
    }

    fun wav(pcm: ByteArray, sampleRate: Int): ByteArray {
        val out = ByteArrayOutputStream(pcm.size + 44)
        fun le32(value: Int) = out.write(
            byteArrayOf(
                value.toByte(), (value shr 8).toByte(),
                (value shr 16).toByte(), (value shr 24).toByte(),
            )
        )
        fun le16(value: Int) = out.write(byteArrayOf(value.toByte(), (value shr 8).toByte()))
        out.write("RIFF".toByteArray()); le32(36 + pcm.size); out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); le32(16); le16(1); le16(1)
        le32(sampleRate); le32(sampleRate * 2); le16(2); le16(16)
        out.write("data".toByteArray()); le32(pcm.size); out.write(pcm)
        return out.toByteArray()
    }

    fun recognize(pcm: ByteArray, cfg: Config): String {
        val key = cfg.openAiApiKey.trim()
        if (key.isBlank()) throw OpenAiException("OpenAI API ključ nije podešen.")
        if (pcm.isEmpty()) throw OpenAiException("Snimak je prazan.")
        if (pcm.size < MIN_AUDIO_BYTES) throw OpenAiException("Snimak je prekratak.")

        val audio = encode(pcm, cfg.sampleRate)
        if (audio.bytes.size > MAX_FILE_BYTES) {
            throw OpenAiException("Audio fajl je prevelik za OpenAI (najviše 25 MB).")
        }

        return recognizeEncoded(audio, cfg, pcm.size / 2.0 / cfg.sampleRate)
    }

    /**
     * Transkribuje audio koji je došao iz druge aplikacije. OpenAI prihvata
     * originalni format (mp3, m4a, ogg/opus, wav...), pa nema potrebe da ga
     * prvo pretvaramo u PCM i time nepotrebno povećavamo fajl.
     */
    fun recognizeFile(
        bytes: ByteArray,
        fileName: String,
        contentType: String?,
        seconds: Double,
        cfg: Config,
    ): String {
        val key = cfg.openAiApiKey.trim()
        if (key.isBlank()) throw OpenAiException("OpenAI API ključ nije podešen.")
        if (bytes.size < 128) throw OpenAiException("Audio fajl je prazan ili prekratak.")
        if (bytes.size > MAX_FILE_BYTES) {
            throw OpenAiException("Audio fajl je prevelik za OpenAI (najviše 25 MB).")
        }
        val rawSafeName = fileName
            .replace(Regex("[^A-Za-z0-9._-]"), "_")
            .ifBlank { "shared-audio" }
        // WhatsApp šalje Opus u Ogg kontejneru kao „.opus“. Endpoint za
        // transkripciju prihvata Ogg, ali odbija sam nastavak „.opus“, pa se
        // fajl pri slanju označava kao Ogg bez menjanja audio bajtova.
        val isOpus = rawSafeName.substringAfterLast('.', "").equals("opus", true) ||
            contentType.equals("audio/opus", ignoreCase = true)
        val safeName = if (isOpus) {
            rawSafeName.substringBeforeLast('.', rawSafeName) + ".ogg"
        } else {
            rawSafeName
        }
        val type = if (isOpus) {
            "audio/ogg"
        } else {
            contentType
                ?.takeIf { it.startsWith("audio/", ignoreCase = true) }
                ?: mimeFromName(safeName)
        }
        return recognizeEncoded(
            EncodedAudio(bytes, safeName, type), cfg, seconds.coerceAtLeast(0.0),
        )
    }

    private fun recognizeEncoded(
        audio: EncodedAudio,
        cfg: Config,
        seconds: Double,
    ): String {
        val key = cfg.openAiApiKey.trim()
        if (key.isBlank()) throw OpenAiException("OpenAI API ključ nije podešen.")
        if (audio.bytes.size > MAX_FILE_BYTES) {
            throw OpenAiException("Audio fajl je prevelik za OpenAI (najviše 25 MB).")
        }

        val fields = linkedMapOf(
            "model" to MODEL,
            // gpt-transcribe podržava niz mogućih jezika; ime polja u
            // multipart zahtevu mora zato biti languages[].
            "languages[]" to "sr",
            "prompt" to prompt(cfg.openAiOutputScript),
            "response_format" to "json",
            "temperature" to "0",
        )
        val (body, contentType) = multipart(fields, audio)
        return withRetry {
            val reply = request(body, contentType, key, seconds, cfg)
            val text = runCatching { JSONObject(reply).optString("text").trim() }
                .getOrElse { throw OpenAiException("OpenAI je vratio neispravan odgovor.", true) }
            text.ifBlank { throw OpenAiException("OpenAI nije vratio prepis.", true) }
        }
    }

    private fun mimeFromName(name: String): String = when (name.substringAfterLast('.', "").lowercase()) {
        "mp3" -> "audio/mpeg"
        "m4a", "mp4", "aac" -> "audio/mp4"
        "ogg", "opus" -> "audio/ogg"
        "flac" -> "audio/flac"
        "wav" -> "audio/wav"
        else -> "application/octet-stream"
    }

    private fun encode(pcm: ByteArray, sampleRate: Int): EncodedAudio {
        val flac = FlacEncoder.encode(pcm, sampleRate)
        return if (flac != null) {
            EncodedAudio(flac, "diktat.flac", "audio/flac")
        } else {
            EncodedAudio(wav(pcm, sampleRate), "diktat.wav", "audio/wav")
        }
    }

    private fun multipart(
        fields: Map<String, String>, audio: EncodedAudio,
    ): Pair<ByteArray, String> {
        val boundary = "----diktat-${UUID.randomUUID().toString().replace("-", "")}"
        val out = ByteArrayOutputStream(audio.bytes.size + 1024)
        fun line(value: String) { out.write(value.toByteArray(Charsets.UTF_8)) }
        for ((name, value) in fields) {
            line("--$boundary\r\n")
            line("Content-Disposition: form-data; name=\"$name\"\r\n\r\n")
            line("$value\r\n")
        }
        line("--$boundary\r\n")
        line("Content-Disposition: form-data; name=\"file\"; filename=\"${audio.fileName}\"\r\n")
        line("Content-Type: ${audio.contentType}\r\n\r\n")
        out.write(audio.bytes)
        line("\r\n--$boundary--\r\n")
        return out.toByteArray() to "multipart/form-data; boundary=$boundary"
    }

    private fun <T> withRetry(block: () -> T): T {
        var last: OpenAiException? = null
        for (attempt in 0..MAX_RETRIES) {
            try {
                return block()
            } catch (exc: OpenAiException) {
                if (!exc.retryable || attempt == MAX_RETRIES) throw exc
                last = exc
                Thread.sleep(RETRY_WAIT_MS * (attempt + 1L).coerceAtMost(5L))
            }
        }
        throw last ?: OpenAiException("OpenAI transkripcija nije uspela.")
    }

    private fun request(
        body: ByteArray,
        contentType: String,
        key: String,
        seconds: Double,
        cfg: Config,
    ): String {
        val conn = try {
            (URL(ENDPOINT).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 15_000
                readTimeout = 180_000
                setRequestProperty("Authorization", "Bearer $key")
                setRequestProperty("Content-Type", contentType)
                setRequestProperty("User-Agent", "Diktat/1.0")
                setFixedLengthStreamingMode(body.size)
            }
        } catch (exc: IOException) {
            throw networkError(exc)
        }

        try {
            try {
                conn.outputStream.use { it.write(body) }
                val code = conn.responseCode
                val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                val reply = stream?.bufferedReader()?.readText().orEmpty()
                if (code !in 200..299) {
                    throw OpenAiException(explain(code, reply), retryable = code == 408 || code == 429 || code >= 500)
                }
                cfg.addTraffic(
                    body.size.toLong(), reply.toByteArray().size.toLong(), seconds,
                )
                return reply
            } catch (exc: OpenAiException) {
                throw exc
            } catch (exc: IOException) {
                throw networkError(exc)
            }
        } finally {
            conn.disconnect()
        }
    }

    private fun networkError(exc: IOException): OpenAiException = when (exc) {
        is SocketTimeoutException -> OpenAiException("OpenAI zahtev je istekao.", retryable = true)
        is UnknownHostException -> OpenAiException("Nema internet veze za OpenAI.", retryable = true)
        else -> OpenAiException("Mrežna greška pri OpenAI transkripciji.", retryable = true)
    }

    private fun explain(code: Int, detail: String): String {
        val apiMessage = runCatching {
            JSONObject(detail).optJSONObject("error")?.optString("message").orEmpty()
        }.getOrDefault("").trim()
        return when (code) {
            401, 403 -> "OpenAI je odbio API ključ (HTTP $code)."
            413 -> "Audio fajl je prevelik za OpenAI (HTTP 413)."
            429 -> "OpenAI je ograničio broj zahteva (HTTP 429)."
            400 -> "OpenAI je odbio audio ili parametre (HTTP 400)." +
                if (apiMessage.isBlank()) "" else " $apiMessage"
            else -> "OpenAI je vratio HTTP $code." +
                if (apiMessage.isBlank()) "" else " $apiMessage"
        }
    }
}
