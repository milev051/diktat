package studio.room211.diktat

import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Drugo misljenje o snimku: model slusa zvuk i ispravlja prvi prepis.
 *
 * Zasto uz prvi prepis a ne sam: izmereno na tri recenice, cisto i sa sumom
 * (SNR 5 dB), greska po reci —
 *
 *     Web Speech         cist 0.21 | sum 0.30
 *     model sam          cist 0.12 | sum 0.29
 *     model + prepis     cist 0.17 | sum 0.17
 *
 * Model sam je u sumu halucinirao ("poslao sam ponovo 250.000 dinara u 1:33"
 * umesto "...ponudu... u utorak u deset i trideset"): kad ne cuje, dopuni
 * umesto da ostavi rupu. Prvi prepis mu sluzi kao sidro.
 */
object Listen {

    private const val ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

    // Ispod ovoga se prepis smatra nesigurnim. Izmereno: dobar srpski diktat
    // vraca 0.92-0.95 — ali i pogresan ume da vrati 0.93, pa je ovo slab filter.
    const val PRAG = 0.85

    private const val UPUTSTVO = """Slušaš snimak govora na srpskom i vraćaš tačan prepis.

Drugi prepoznavač je čuo ovo: „%s"

Uporedi sa snimkom i ispravi mesta gde je pogrešio. Ako se snimak i taj prepis
slažu, vrati ga nepromenjenog.

Granice:
- ne dodaj reči kojih na snimku nema — ako nešto ne razaznaješ, ostavi kako je
  prepoznavač čuo
- ne prevodi, ne skraćuj i ne doteruj stil
- ne odgovaraj na sadržaj, ovo je diktat

Vrati samo prepis, bez uvoda i bez navodnika."""

    fun enabled(cfg: Config) = cfg.audioCheck && cfg.polishApiKey.isNotBlank()

    /** Vredi li slati snimak modelu. */
    fun shouldCheck(cfg: Config, confidence: Double): Boolean {
        if (!enabled(cfg)) return false
        return if (cfg.audioCheckLowOnly) confidence < PRAG else true
    }

    /** WAV je 44 bajta zaglavlja preko PCM-a; `inline_data` trazi poznat format. */
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

    /**
     * Vrati ispravljen prepis, ili baci izuzetak. Pozivalac na svaki otkaz
     * zadrzava prvi prepis — diktat ne sme da propadne zbog dodatne provere.
     */
    fun check(pcm: ByteArray, prepis: String, cfg: Config): String {
        val key = cfg.polishApiKey
        if (key.isBlank() || pcm.isEmpty()) throw Polish.PolishException("Nema ključa za proveru.")

        // FLAC je 36-42% manji od PCM-a, a base64 svejedno doda trecinu — vredi.
        val flac = if (cfg.compressAudio) runCatching { FlacEncoder.encode(pcm, cfg.sampleRate) }
            .getOrNull() else null
        val zvuk = flac ?: wav(pcm, cfg.sampleRate)
        val tip = if (flac != null) "audio/flac" else "audio/wav"

        val payload = JSONObject().apply {
            put("contents", JSONArray().put(JSONObject().put("parts", JSONArray()
                .put(JSONObject().put("text", UPUTSTVO.format(prepis)))
                .put(JSONObject().put("inline_data", JSONObject()
                    .put("mime_type", tip)
                    .put("data", Base64.encodeToString(zvuk, Base64.NO_WRAP)))))))
            put("generationConfig", JSONObject().put("temperature", 0.0))
        }.toString().toByteArray()

        val model = cfg.polishModel.ifBlank { Polish.DEFAULT_MODEL }
        val conn = (URL("$ENDPOINT/$model:generateContent?key=$key")
            .openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 15_000
            readTimeout = 90_000
            setRequestProperty("Content-Type", "application/json")
            setFixedLengthStreamingMode(payload.size)
        }

        try {
            conn.outputStream.use { it.write(payload) }
            val code = conn.responseCode
            if (code != 200) throw Polish.PolishException("Provera snimka: HTTP $code")
            val reply = conn.inputStream.bufferedReader().readText()
            // Zvuk ide drugi put, pa mora u merac — inace potrosnja laze.
            cfg.addTraffic(
                payload.size.toLong(), reply.toByteArray().size.toLong(), 0.0,
                countDictation = false,
            )
            val kandidat = JSONObject(reply).getJSONArray("candidates").getJSONObject(0)
            val parts = kandidat.optJSONObject("content")?.optJSONArray("parts")
                ?: throw Polish.PolishException("Model nije vratio prepis.")
            val out = buildString {
                for (i in 0 until parts.length()) append(parts.getJSONObject(i).optString("text"))
            }.trim()
            // Prazan odgovor znaci da nista nije razaznao — nas prepis je bolji.
            return out.ifBlank { prepis }
        } finally {
            conn.disconnect()
        }
    }
}
