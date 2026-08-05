package studio.room211.diktat

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Formalni rezim: doterivanje transkripta jezickim modelom.
 *
 * Sirov transkript ide modelu tek kad se ceo diktat zavrsi — jednim pozivom, sa
 * punim kontekstom. Po segmentu bi model video krhotine i izmisljao krajeve
 * recenica, a broj poziva bi skocio sa jednog na stotinak po diktatu.
 *
 * Model dobija tekst nedirnut: skracenice i skidanje kvacica se u ovom rezimu
 * ne primenjuju, jer mu otezavaju citanje.
 */
object Polish {

    private const val ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
    const val DEFAULT_MODEL = "gemini-flash-lite-latest"

    // Izmereno: flash-lite doteruje za ~1s i ne dira reci; gemini-3.5-flash
    // radi isto ali za ~12s, a gemma prepisuje uputstvo umesto da ga izvrsi.
    private val PROMPT = """
        Dobijaš sirov transkript govora na srpskom, bez interpunkcije i sve malim slovima.

        Tvoj posao je SAMO oblikovanje:
        - dodaj interpunkciju i velika slova
        - vrati kvačice (č ć ž š đ) gde po pravopisu treba
        - podeli na rečenice i pasuse gde je prirodno

        Zabranjeno ti je:
        - da menjaš, dodaješ ili izbacuješ ijednu reč
        - da preformulišeš, skraćuješ ili doteruješ stil
        - da odgovaraš na sadržaj teksta

        Ako neka reč deluje pogrešno prepoznato, OSTAVI JE KAKVA JE.
        Vrati samo oblikovan tekst, bez ikakvog uvoda i bez navodnika.
    """.trimIndent()

    class PolishException(message: String) : Exception(message)

    fun available(cfg: Config) = cfg.polishApiKey.isNotBlank()

    fun polish(text: String, cfg: Config): String {
        if (text.isBlank()) return text
        val key = cfg.polishApiKey
        if (key.isBlank()) throw PolishException("Nema API ključa za doterivanje.")

        val model = cfg.polishModel.ifBlank { DEFAULT_MODEL }
        val payload = JSONObject().apply {
            put("systemInstruction", JSONObject().put("parts",
                org.json.JSONArray().put(JSONObject().put("text", PROMPT))))
            put("contents", org.json.JSONArray().put(
                JSONObject().put("parts",
                    org.json.JSONArray().put(JSONObject().put("text", text)))))
            put("generationConfig", JSONObject().put("temperature", 0.0))
        }.toString().toByteArray()

        val conn = (URL("$ENDPOINT/$model:generateContent?key=$key")
            .openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 15_000
            readTimeout = 60_000
            setRequestProperty("Content-Type", "application/json")
            setFixedLengthStreamingMode(payload.size)
        }

        try {
            conn.outputStream.use { it.write(payload) }
            val code = conn.responseCode
            if (code != 200) throw PolishException(explain(code))
            val reply = conn.inputStream.bufferedReader().readText()
            val parts = JSONObject(reply)
                .getJSONArray("candidates").getJSONObject(0)
                .getJSONObject("content").getJSONArray("parts")
            val out = buildString {
                for (i in 0 until parts.length()) append(parts.getJSONObject(i).optString("text"))
            }.trim()
            // Prazan odgovor je gori od nedoteranog teksta.
            return out.ifBlank { text }
        } finally {
            conn.disconnect()
        }
    }

    private fun explain(code: Int) = when (code) {
        400, 403 -> "Model je odbio zahtev ($code) — proveri API ključ."
        404 -> "Traženi model ne postoji na ovom ključu."
        429 -> "Previše zahteva ka modelu (429)."
        else -> "Model je vratio HTTP $code."
    }
}
