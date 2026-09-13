package studio.room211.diktat

import org.json.JSONObject
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread

/**
 * `gemini-3.5-transcribe-live` kao izvor transkripcije, preko Live API-ja.
 *
 * Prevod `dictate/geministt.py` — ako se logika menja, menja se na oba mesta.
 *
 * Zasto bas Live varijanta: besplatne kvote (AI Studio, 28.08.2026) su za
 * `gemini-3.5-transcribe` 3 u minuti / 25 dnevno, a za Live bez granice. 25
 * dnevno ne znaci nista za svakodnevni rad, pa obicna varijanta nije ni
 * ugradjena.
 *
 * **Zvuk se strimuje DOK snimanje traje.** Izmereno na 64.7s zvuka: slanje
 * posle Stop-a ostavlja 15.6s cekanja, slanje u toku 0.0s. Cena je ista, jer
 * se naplacuje zvuk a zvuk je isti. Mana: komadi sa mikrofona se citaju samo
 * jednom, pa drugi pokusaj nema sta da posalje — neuspeo Live diktat propada,
 * zvuk se nigde ne cuva.
 *
 * Kljuc je isti `polishApiKey` iz AI Studio — ne pravi se drugi za istu uslugu.
 */
object GeminiStt {

    class GeminiSttException(message: String, val retryable: Boolean = false) : Exception(message)

    const val LIVE_MODEL = "gemini-3.5-transcribe-live"
    const val WS_ENDPOINT =
        "wss://generativelanguage.googleapis.com/ws/" +
            "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"

    /** Live API trazi komade od ~100ms; veci kasni, manji trosi okvire uzalud. */
    const val LIVE_CHUNK_MS = 100

    /**
     * Rep tisine bez kog se POSLEDNJA izgovorena celina nikad ne finalizuje.
     * Izmereno na snimku od 19s sa dve pauze: bez repa stignu 2 od 3 konacna
     * prepisa, sa 2s tisine sva tri.
     */
    const val LIVE_TAIL_SILENCE = 2.0

    /**
     * Posle zvuka server ne zatvara vezu: salje prazne poruke dok radi, pa
     * stane. Tisina je zato jedini znak da je gotov — `turnComplete` ne
     * postoji, provereno na zivom endpointu.
     *
     * Dve strpljivosti, jer nisu isti slucajevi:
     *   IDLE  — celina je zapoceta a nije finalizovana; prekid bi je odsekao.
     *   QUIET — poslednja celina je finalizovana i nista novo nije poceto.
     *
     * Izmereno: poslednji prepis stigne 0.5s posle Stop-a bez obzira na duzinu
     * diktata, a najveci razmak izmedju poruka u strim rezimu je 0.47s — 1.0s
     * je dakle dvostruka rezerva. Ukupno cekanje pada sa 3.5s na 1.5s.
     */
    const val LIVE_IDLE_MS = 3_000
    const val LIVE_QUIET_MS = 1_000

    const val MIN_AUDIO_BYTES = 6_400          // 0.2 s mono PCM-a na 16 kHz
    private const val CONNECT_TIMEOUT_MS = 30_000

    fun enabled(cfg: Config): Boolean = cfg.transcriptionProvider == "gemini_live"

    fun modelFor(): String = LIVE_MODEL

    private fun key(cfg: Config): String {
        val k = cfg.polishApiKey.trim()
        if (k.isBlank()) {
            throw GeminiSttException("Gemini API kljuc nije podesen.", retryable = false)
        }
        return k
    }

    /**
     * Nagovestaj jezika; prazno podesavanje pada na `sr-RS`.
     *
     * Prazan spisak bi znacio „sam prepoznaj jezik", sto je ovde losije: diktat
     * je na srpskom, a bez nagovestaja model ume da odluta na hrvatski.
     */
    fun languageCodes(cfg: Config): List<String> =
        listOf(cfg.language.trim().ifBlank { "sr-RS" })

    fun liveSetup(cfg: Config): JSONObject {
        val setup = JSONObject()
            .put("model", "models/$LIVE_MODEL")
            .put("generationConfig", JSONObject().put(
                "responseModalities", org.json.JSONArray(listOf("TEXT"))
            ))
            .put("inputAudioTranscription", JSONObject().put(
                "languageCodes", org.json.JSONArray(languageCodes(cfg))
            ))
        return JSONObject().put("setup", setup)
    }

    private fun serverContent(poruka: JSONObject): JSONObject? =
        poruka.optJSONObject("serverContent") ?: poruka.optJSONObject("server_content")

    /** KONACAN prepis jedne izgovorene celine, ili prazno. */
    fun liveText(poruka: JSONObject): String {
        val s = serverContent(poruka) ?: return ""
        for (ime in listOf("inputTranscription", "input_transcription")) {
            val deo = s.optJSONObject(ime) ?: continue
            val t = deo.optString("text", "")
            if (t.isNotEmpty()) return t
        }
        return ""
    }

    /**
     * Medjurezultat — koristi se SAMO ako celina nikad ne dobije konacan
     * prepis. Inace bi udvojio reci.
     */
    fun liveInterim(poruka: JSONObject): String {
        val s = serverContent(poruka) ?: return ""
        for (ime in listOf("interimInputTranscription", "interim_input_transcription")) {
            val deo = s.optJSONObject(ime) ?: continue
            val t = deo.optString("text", "")
            if (t.isNotEmpty()) return t
        }
        return ""
    }

    /** Razlog iz CLOSE okvira; bez njega otkaz izgleda kao nasumican prekid. */
    fun zatvoreno(ws: WSock): String = when {
        ws.closeReason.isNotEmpty() -> "Gemini Transcribe Live: ${ws.closeReason}"
        ws.closeCode != null -> "Gemini Transcribe Live: veza zatvorena (${ws.closeCode})"
        else -> "Gemini Transcribe Live: veza zatvorena bez odgovora"
    }

    /**
     * 1007 (neispravan podatak) nosi i „API key not valid" i pogresan `setup` —
     * oba su nasa greska, drugi pokusaj bi dao isto.
     */
    fun prolazno(ws: WSock): Boolean = when {
        ws.closeCode == 1007 -> false
        else -> !ws.closeReason.lowercase().contains("api key")
    }

    /**
     * Prepisi zvuk koji stize iz `komadi` — dok korisnik jos prica.
     *
     * `komadi` vraca `null` kad snimanje stane. Lista sa jednim elementom daje
     * staro ponasanje (sve odjednom), pa oba puta idu kroz isti kod.
     */
    fun recognizeStream(
        cfg: Config,
        onUpdate: ((String) -> Unit)? = null,
        komadi: () -> ByteArray?,
    ): String {
        val rate = cfg.sampleRate
        // 16-bit mono: dva bajta po semplu, pa je komad od 100ms rate/10*2.
        val korak = maxOf(2, (rate / 1000) * LIVE_CHUNK_MS * 2)
        val delovi = mutableListOf<String>()
        val enc = Base64.getEncoder()

        WSock("$WS_ENDPOINT?key=${key(cfg)}", CONNECT_TIMEOUT_MS).use { ws ->
            try {
                ws.connect()
                ws.sendText(liveSetup(cfg).toString())
                val prvi = ws.recvText()
                    ?: throw GeminiSttException(zatvoreno(ws), prolazno(ws))
                val odgovor = JSONObject(prvi)
                if (!odgovor.has("setupComplete") && !odgovor.has("setup_complete")) {
                    throw GeminiSttException(
                        "Live API nije prihvatio podesavanje: ${prvi.take(200)}",
                        retryable = false,
                    )
                }

                fun posalji(data: ByteArray) {
                    var i = 0
                    while (i < data.size) {
                        val kraj = minOf(i + korak, data.size)
                        val audio = JSONObject()
                            .put("data", enc.encodeToString(data.copyOfRange(i, kraj)))
                            .put("mimeType", "audio/pcm;rate=$rate")
                        ws.sendText(
                            JSONObject().put(
                                "realtimeInput", JSONObject().put("audio", audio)
                            ).toString()
                        )
                        i = kraj
                    }
                }

                if (onUpdate != null) {
                    return streamWithPreview(ws, komadi, ::posalji, korak, rate, onUpdate)
                }

                // Ostatak koji nije pun komad nosi se u sledeci prolaz:
                // mikrofon ne isporucuje na granici od 100ms, a slanje krnjih
                // okvira razbija prepoznavanje po sredini reci.
                var ostatak = ByteArray(0)
                while (true) {
                    val komad = komadi() ?: break
                    if (komad.isEmpty()) continue
                    ostatak += komad
                    val celi = ostatak.size - (ostatak.size % korak)
                    if (celi > 0) {
                        posalji(ostatak.copyOfRange(0, celi))
                        ostatak = ostatak.copyOfRange(celi, ostatak.size)
                    }
                }
                // Rep tisine: bez njega poslednja celina ostane na medjurezultatu.
                posalji(ostatak + ByteArray((rate * LIVE_TAIL_SILENCE).toInt() * 2))
                ws.sendText(
                    JSONObject().put(
                        "realtimeInput", JSONObject().put("audioStreamEnd", true)
                    ).toString()
                )

                // Od sada tisina znaci "gotov je", pa se ceka kratko.
                ws.setTimeout(LIVE_QUIET_MS)
                var posleZadnjeg = ""
                var produzeno = false
                while (true) {
                    val sirovo = try {
                        ws.recvText()
                    } catch (e: WSock.WSException) {
                        if (posleZadnjeg.isNotEmpty() && !produzeno) {
                            // Celina je u toku: video se medjurezultat bez svog
                            // finala. Prekid bi je odsekao, pa joj se jednom da
                            // pun rok.
                            produzeno = true
                            ws.setTimeout(LIVE_IDLE_MS)
                            continue
                        }
                        if (delovi.isNotEmpty() || posleZadnjeg.isNotEmpty()) break
                        throw e
                    }
                    if (sirovo == null) {
                        if (delovi.isEmpty() && ws.closeReason.isNotEmpty()) {
                            // Zatvaranje bez ijednog prepisa je otkaz, ne kraj.
                            throw GeminiSttException(zatvoreno(ws), prolazno(ws))
                        }
                        break
                    }
                    val poruka = JSONObject(sirovo)
                    if (poruka.has("error")) {
                        throw GeminiSttException(
                            "Live API: ${poruka.opt("error")?.toString()?.take(200)}",
                            retryable = true,
                        )
                    }
                    val tekst = liveText(poruka)
                    if (tekst.isNotEmpty()) {
                        delovi.add(tekst)
                        posleZadnjeg = ""
                        produzeno = false
                        ws.setTimeout(LIVE_QUIET_MS)
                        continue
                    }
                    // `generationComplete` stize posle SVAKE izgovorene celine,
                    // ne na kraju diktata — prekid na njemu bi odbacio sve posle
                    // prve pauze.
                    val medju = liveInterim(poruka)
                    if (medju.isNotEmpty()) posleZadnjeg = medju
                }
                if (posleZadnjeg.isNotEmpty()) delovi.add(posleZadnjeg)
            } catch (e: WSock.WSException) {
                throw GeminiSttException("Gemini Transcribe Live: ${e.message}", e.retryable)
            }
        }
        return delovi.map { it.trim() }.filter { it.isNotEmpty() }.joinToString(" ").trim()
    }

    private fun streamWithPreview(
        ws: WSock,
        komadi: () -> ByteArray?,
        posalji: (ByteArray) -> Unit,
        korak: Int,
        rate: Int,
        onUpdate: (String) -> Unit,
    ): String {
        val delovi = mutableListOf<String>()
        var interim = ""
        val sent = AtomicBoolean(false)
        val finished = CountDownLatch(1)
        val error = AtomicReference<Exception?>(null)
        ws.setTimeout(500)

        fun prikazi() {
            val text = (delovi + interim).filter { it.isNotBlank() }.joinToString(" ").trim()
            runCatching { onUpdate(text) }
        }

        thread(name = "gemini-live-preview", isDaemon = true) {
            var lastMessage = System.currentTimeMillis()
            try {
                while (true) {
                    val raw = try {
                        ws.recvText()
                    } catch (_: WSock.WSTimeout) {
                        if (!sent.get()) continue
                        val waitMs = if (interim.isNotBlank()) LIVE_IDLE_MS else LIVE_QUIET_MS
                        if (System.currentTimeMillis() - lastMessage >= waitMs) {
                            if (delovi.isNotEmpty() || interim.isNotBlank()) break
                            throw GeminiSttException("Gemini Transcribe Live nije vratio prepis.", true)
                        }
                        continue
                    }
                    if (raw == null) {
                        if (delovi.isEmpty() && interim.isBlank() && ws.closeReason.isNotEmpty()) {
                            throw GeminiSttException(zatvoreno(ws), prolazno(ws))
                        }
                        break
                    }
                    val message = JSONObject(raw)
                    if (message.has("error")) {
                        throw GeminiSttException(
                            "Live API: ${message.opt("error")?.toString()?.take(200)}", true
                        )
                    }
                    lastMessage = System.currentTimeMillis()
                    val final = liveText(message)
                    if (final.isNotBlank()) {
                        delovi.add(final)
                        interim = ""
                        prikazi()
                    } else {
                        val temporary = liveInterim(message)
                        if (temporary.isNotBlank()) {
                            interim = temporary
                            prikazi()
                        }
                    }
                }
            } catch (e: Exception) {
                error.set(e)
            } finally {
                finished.countDown()
            }
        }

        var remainder = ByteArray(0)
        try {
            while (true) {
                error.get()?.let { throw it }
                val chunk = komadi() ?: break
                if (chunk.isEmpty()) continue
                remainder += chunk
                val whole = remainder.size - (remainder.size % korak)
                if (whole > 0) {
                    posalji(remainder.copyOfRange(0, whole))
                    remainder = remainder.copyOfRange(whole, remainder.size)
                }
            }
            posalji(remainder + ByteArray((rate * LIVE_TAIL_SILENCE).toInt() * 2))
            ws.sendText(JSONObject().put(
                "realtimeInput", JSONObject().put("audioStreamEnd", true)
            ).toString())
            sent.set(true)
            if (!finished.await(
                    (LIVE_IDLE_MS + LIVE_QUIET_MS + 2_000).toLong(), TimeUnit.MILLISECONDS
                )) {
                throw GeminiSttException("Gemini Transcribe Live nije završio odgovor.", true)
            }
            error.get()?.let { throw it }
            if (interim.isNotBlank()) delovi.add(interim)
            return delovi.map { it.trim() }.filter { it.isNotEmpty() }.joinToString(" ").trim()
        } finally {
            sent.set(true)
        }
    }

    /** Gotov snimak — zvuk se salje odjednom, posle Stop-a. */
    fun recognize(pcm: ByteArray, cfg: Config): String {
        if (pcm.isEmpty()) return ""
        if (pcm.size < MIN_AUDIO_BYTES) {
            throw GeminiSttException("Snimak je prekratak za Gemini Transcribe.", false)
        }
        var poslato = false
        return recognizeStream(cfg) { if (poslato) null else pcm.also { poslato = true } }
    }

    /**
     * Lokalna pravila. Endpoint za `sr-RS` vraca CIRILICU, i to nedosledno —
     * izmereno u istom diktatu i „тест тест" i „Test test". Aplikacija je
     * latinicna, pa se pismo poravnava pre svega ostalog.
     */
    fun postProcess(text: String, cfg: Config): String {
        var out = OpenAiTranscription.toLatin(text).trim()
        if (out.isNotEmpty()) out = TextPolish.applyBlocks(out, cfg)
        return if (out.isNotEmpty() && cfg.trailingSpace) "$out " else out
    }
}
