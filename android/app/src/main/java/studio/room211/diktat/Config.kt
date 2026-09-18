package studio.room211.diktat

import android.content.Context
import org.json.JSONArray
import kotlin.math.roundToLong

/** Podesavanja, ista imena i podrazumevane vrednosti kao u macOS verziji. */
class Config(context: Context) {

    private val prefs = context.getSharedPreferences("diktat", Context.MODE_PRIVATE)

    companion object {
        /** Izvori transkripcije; spisak stoji na jednom mestu. */
        val PROVIDERS = setOf("google", "openai", "gemini_live")

        // Kljucevi se NE ugraduju u APK. Repozitorijum se deli, pa bi ugraden
        // kljuc znacio da svaka instalacija trosi tudji nalog, i da kljuc
        // zauvek ostane u istoriji commita. Korisnik ga unosi u aplikaciji;
        // cuva se u SharedPreferences-u i nadogradnja ga ne dira.
    }

    /**
     * Provera novog GitHub izdanja cim se aplikacija otvori.
     *
     * Jedan mali GET, bez preuzimanja; APK se skida tek kad se pritisne
     * dugme. Iskljuceno znaci da se proverava samo rucno.
     */
    var updateCheckOnStart: Boolean
        get() = prefs.getBoolean("update_check_on_start", true)
        set(v) = prefs.edit().putBoolean("update_check_on_start", v).apply()

    var language: String
        get() = prefs.getString("language", "sr-RS")!!
        set(v) = prefs.edit().putString("language", v).apply()

    var apiKey: String
        get() = prefs.getString("api_key", "")!!
        set(v) = prefs.edit().putString("api_key", v).apply()

    /**
     * Provider osnovnog transkribovanja; Google ostaje podrazumevan.
     *
     * "gemini_live" je `gemini-3.5-transcribe-live` preko Live API-ja. Obicna
     * varijanta `gemini-3.5-transcribe` NIJE ugradjena: na besplatnom nivou ima
     * 25 zahteva dnevno, sto za svakodnevni rad ne znaci nista. Nepoznata
     * vrednost bezbedno pada na Google.
     */
    var transcriptionProvider: String
        get() = when (prefs.getString("transcription_provider", "google")) {
            "openai" -> "openai"
            "gemini_live" -> "gemini_live"
            else -> "google"
        }
        set(v) = prefs.edit().putString(
            "transcription_provider",
            if (v in PROVIDERS) v else "google",
        ).apply()

    /** Ključ se unosi u aplikaciji; nema ugrađenog OpenAI ključa. */
    var openAiApiKey: String
        get() = prefs.getString("openai_api_key", "")!!
        set(v) = prefs.edit().putString("openai_api_key", v.trim()).apply()

    /** OpenAI može da snima dugo, ali uvek ima sigurnosni limit od 60 minuta. */
    var openAiLongRecording: Boolean
        get() = prefs.getBoolean("openai_long_recording", true)
        set(v) = prefs.edit().putBoolean("openai_long_recording", v).apply()

    val openAiMaxSeconds: Int
        get() = prefs.getInt("openai_max_seconds", 3600).coerceIn(60, 3600)

    /**
     * Koji režim određuje granicu snimanja za trenutno izabranog provajdera.
     *
     * Gemini Live je UVEK dug: zvuk se strimuje dok snimanje traje, pa ga
     * pokreće ista petlja bez obzira na „neprekidno" — a granica od 30 s je
     * ograničenje Web Speech endpointa i ovde nema šta da radi.
     */
    val longRecording: Boolean
        get() = when (transcriptionProvider) {
            "openai" -> openAiLongRecording
            "gemini_live" -> true
            else -> continuous
        }

    /** Auto = model bira pismo; ostale vrednosti traže određeno pismo. */
    var openAiOutputScript: String
        get() = when (prefs.getString("openai_output_script", "auto")) {
            "cyrillic" -> "cyrillic"
            "latin" -> "latin"
            else -> "auto"
        }
        set(v) = prefs.edit().putString(
            "openai_output_script", when (v) {
                "cyrillic", "latin" -> v
                else -> "auto"
            }
        ).apply()

    /** Независно: сва слова мала, без обзира на интерпункцију. */
    var lowercase: Boolean
        get() = if (prefs.contains("lowercase")) {
            prefs.getBoolean("lowercase", true)
        } else {
            prefs.getString("text_style", "spoken") != "written"
        }
        set(v) = prefs.edit().putBoolean("lowercase", v).apply()

    /** Независно: уклони интерпункцију, уз очување сепаратора у бројевима. */
    var stripPunctuation: Boolean
        get() = if (prefs.contains("strip_punctuation")) {
            prefs.getBoolean("strip_punctuation", true)
        } else {
            prefs.getString("text_style", "spoken") != "written"
        }
        set(v) = prefs.edit().putBoolean("strip_punctuation", v).apply()

    /** Uvek iskljuceno: `pFilter=0`. Maskiranje psovki niko nije koristio. */
    val profanityFilter = false

    /** č ć ž š đ -> c c z s dj. Podrazumevano iskljuceno, kao na Mac-u. */
    var asciiDiacritics: Boolean
        get() = prefs.getBoolean("ascii_diacritics", false)
        set(v) = prefs.edit().putBoolean("ascii_diacritics", v).apply()

    /**
     * "obicno"     — jedan snimak do maxSeconds, pa obrada
     * "neprekidno" — bez vremenskog ogranicenja; sece na pauzama i salje
     *                delove dok snimanje tece dalje
     */
    var continuous: Boolean
        get() = prefs.getBoolean("continuous", true)
        set(v) = prefs.edit().putBoolean("continuous", v).apply()

    /**
     * Koliko segment mora da traje pre nego sto pauza sme da ga presece.
     * 0 znaci: seci na SVAKOJ pauzi, ma koliko kratka celina bila.
     */
    val segmentAfterSeconds get() = prefs.getInt("segment_after_seconds", 0)
    val pauseSeconds get() = prefs.getFloat("pause_seconds", 0.7f).toDouble()

    /** Sigurnosna granica i za neprekidni rezim — da zaboravljen diktat stane. */
    val continuousMaxSeconds get() = prefs.getInt("continuous_max_seconds", 3600)

    /**
     * Granica bas za Gemini Live, kratka i namerno drugacija od ostalih.
     *
     * Live je jedini izvor koji salje zvuk DOK snimas (~2,5 MB po minutu), pa
     * zaboravljen diktat tu curi podatke sve vreme, a ne tek na kraju. Kod
     * Google-a i OpenAI-ja zaboravljen diktat kosta samo vreme dok neko ne
     * primeti; ovde kosta i mobilni internet. Posle granice se trazi nov
     * pritisak, kao i inace.
     */
    val geminiLiveMaxSeconds: Int
        get() = prefs.getInt("gemini_live_max_seconds", 120).coerceIn(30, 3600)

    var geminiLivePreview: Boolean
        get() = prefs.getBoolean("gemini_live_preview", false)
        set(v) = prefs.edit().putBoolean("gemini_live_preview", v).apply()

    /** Uvek ukljuceno: ako sazimanje ne uspe, salje se sirov zvuk kao i pre. */
    val compressAudio = true

    /** "5.000" -> "5000"; zarez kao decimalni ostaje. */
    /** Uvek ukljuceno: „5.000" -> „5000"; zarez ostaje decimalni. */
    val joinThousands = true

    var abbreviations: Boolean
        get() = prefs.getBoolean("abbreviations", true)
        set(v) = prefs.edit().putBoolean("abbreviations", v).apply()

    /**
     * „Pravilno": sva cetiri prekidaca za izgled teksta odjednom.
     *
     * Nije peto podesavanje nego precica. Svaki od ta cetiri UDALJAVA tekst od
     * pravopisa (mala slova, bez interpunkcije, bez kvacica, skracenice), pa
     * „pravilno" znaci: sva cetiri ugasena. Cetiri klika za prelazak izmedju
     * dva stanja su cetiri prilike da se jedan zaboravi, pa tekst izadje na
     * pola puta.
     *
     * Gasenje NE vraca podrazumevane vrednosti nego bas ono sto je bilo pre
     * ukljucivanja. Razlika je stvarna: `ascii_diacritics` je podrazumevano
     * iskljucen, pa bi povratak na podrazumevano tiho ukinuo izbor onome ko ga
     * drzi upaljenog.
     *
     * Stanje je TRAJNO. Dugme na piluli menja bas ovo, pa izbor ostaje i za
     * sledeci diktat, dok se ne vrati rukom.
     */
    /** Cetiri prekidaca kao jedno stanje; odluke su u `Pravilno`. */
    private var stanjeTeksta: Pravilno.Stanje
        get() = Pravilno.Stanje(lowercase, stripPunctuation, asciiDiacritics, abbreviations)
        set(v) {
            lowercase = v.malaSlova
            stripPunctuation = v.bezInterpunkcije
            asciiDiacritics = v.bezKvacica
            abbreviations = v.skracenice
        }

    var pravilno: Boolean
        get() = stanjeTeksta.pravilno
        set(v) {
            if (v) {
                Pravilno.priUkljucivanju(stanjeTeksta)?.let { zapamti ->
                    prefs.edit()
                        .putBoolean("pravilno_pre_lowercase", zapamti.malaSlova)
                        .putBoolean("pravilno_pre_strip", zapamti.bezInterpunkcije)
                        .putBoolean("pravilno_pre_ascii", zapamti.bezKvacica)
                        .putBoolean("pravilno_pre_abbrev", zapamti.skracenice)
                        .putBoolean("pravilno_pamceno", true)
                        .apply()
                }
                stanjeTeksta = Pravilno.SVE_UGASENO
                return
            }
            val zapamceno = if (prefs.getBoolean("pravilno_pamceno", false)) {
                Pravilno.Stanje(
                    prefs.getBoolean("pravilno_pre_lowercase", true),
                    prefs.getBoolean("pravilno_pre_strip", true),
                    prefs.getBoolean("pravilno_pre_ascii", false),
                    prefs.getBoolean("pravilno_pre_abbrev", true),
                )
            } else {
                null
            }
            stanjeTeksta = Pravilno.priGasenju(zapamceno)
            prefs.edit().putBoolean("pravilno_pamceno", false).apply()
        }

    /**
     * Pravila, jedno po redu, oblik `fraza=skracenica`.
     *
     * Uz pravila se pamti i kako su podrazumevana izgledala kad su sacuvana.
     * Ako se to dvoje poklapa, korisnik ih nije menjao — pa nova verzija sme
     * da donese nova podrazumevana sama. Ako se razlikuje, korisnikova pravila
     * se ne diraju.
     */
    /** Ugrađene fraze su deo builda i na telefonu nisu promenljive. */
    val abbreviationRules: String
        get() = Abbreviations.defaultText()

    /** Uvek ukljuceno: bez polja za unos diktat zavrsi u praznom. */
    val requireInputField = true

    /** Posle uspesnog upisa vrati clipboard kakav je bio — da izdiktirano ne
     *  ostane u istoriji clipboard-a. */
    /** Uvek ukljuceno: tekst se ne ostavlja u clipboard-u kad upis prodje. */
    val restoreClipboard = true

    /** Uvek ukljuceno: bez razmaka se recenice slepe pri nadovezivanju. */
    val trailingSpace = true

    private val historyLimit = 5

    /** Najnoviji uspešni diktati, najviše pet; čuvaju se lokalno. */
    fun history(): List<String> {
        val raw = prefs.getString("history", null) ?: return emptyList()
        return runCatching {
            val json = JSONArray(raw)
            val values = (0 until json.length()).mapNotNull { index ->
                json.optString(index).takeIf { it.isNotBlank() }
            }.take(historyLimit)
            if (values.size < json.length()) {
                val trimmed = JSONArray()
                values.forEach(trimmed::put)
                prefs.edit().putString("history", trimmed.toString()).apply()
            }
            values
        }.getOrDefault(emptyList())
    }

    fun addHistory(text: String) {
        val clean = text.trim()
        if (clean.isBlank()) return
        val values = history().toMutableList()
        values.remove(clean)
        values.add(0, clean)
        while (values.size > historyLimit) values.removeLast()
        val json = JSONArray()
        values.forEach(json::put)
        prefs.edit().putString("history", json.toString()).apply()
    }

    fun clearHistory() {
        prefs.edit().remove("history").apply()
    }

    // --- Formalni rezim ---
    // Kljuc ostaje pri nadogradnji aplikacije: SharedPreferences prezivljava
    // instalaciju preko postojece, dok je paket i potpis isti.
    var polishApiKey: String
        get() = prefs.getString("polish_api_key", "")!!
        set(v) = prefs.edit().putString("polish_api_key", v.trim()).apply()

    /** true = i ispravi ocigledne gramaticke greske, ne samo oblikuj. */
    /**
     * Izgled teksta: jedan izbor umesto tri prekidaca koja su se ponistavala.
     *
     *   "spoken"  — podrazumevano: mala slova, bez interpunkcije
     *   "written" — pravopisno sredjeno; to radi model, pa trazi kljuc
     *
     * Zatecena podesavanja se prevode pri prvom citanju, da niko ne izgubi ono
     * sto je vec namestio.
     */
    var textStyle: String
        get() {
            // Glavni prekidac je uklonjen — izabran alat sam znaci "ukljuceno".
            // Ko ga je imao ugasenog, alate treba i ugasiti pri prvom citanju.
            if (prefs.contains("polish") && !prefs.getBoolean("polish", false)) {
                prefs.edit()
                    .putBoolean("polish_paragraphs", false)
                    .putBoolean("polish_bullets", false)
                    .putBoolean("polish_commas", false)
                    .putBoolean("polish_dedupe", false)
                    .putString("text_style", "spoken")
                    .remove("polish")
                    .apply()
                return "spoken"
            }
            prefs.edit().remove("polish").apply()
            // "raw" je uklonjen: niko ga nije koristio, a bio je treci ishod za
            // isto pitanje. Ko ga je imao, dobija podrazumevano ponasanje.
            prefs.getString("text_style", null)?.let { return if (it == "raw") "spoken" else it }
            val prevedeno = when {
                prefs.getBoolean("polish", false) && prefs.getBoolean("polish_tidy", true) ->
                    "written"
                else -> "spoken"
            }
            prefs.edit().putString("text_style", prevedeno).apply()
            return prevedeno
        }
        set(v) = prefs.edit().putString("text_style", v).apply()

    /** Sredjuje li model interpunkciju i kvacice. */
    val polishTidy: Boolean
        get() = textStyle == "written"

    /**
     * Slobodan opis jezika na kome tekst treba da izadje; prazno = bez prevoda.
     * Spisak jezika ne bi bio dovoljan — korisnik ume da trazi i "pola
     * makedonski pola srpski", sto model razume iz opisa.
     */
    // --- Groq GPT-OSS obrada teksta ---
    var groqApiKey: String
        get() = prefs.getString("groq_api_key", "")!!
        set(v) = prefs.edit().putString("groq_api_key", v.trim()).apply()

    /** Izbaci slucajno udvojene reci i fraze (govorna ispravka). */
    var polishDedupe: Boolean
        get() = prefs.getBoolean("polish_dedupe", false)
        set(v) = prefs.edit().putBoolean("polish_dedupe", v).apply()

    /** Model dodaje samo zareze; ostala interpunkcija ostaje lokalni izbor. */
    var polishCommas: Boolean
        get() = prefs.getBoolean("polish_commas", false)
        set(v) = prefs.edit().putBoolean("polish_commas", v).apply()

    /** Preuredi u spisak tacaka (nalik ASD-STE100); iskljucuje pasuse. */
    var polishBullets: Boolean
        get() = prefs.getBoolean("polish_bullets", false)
        set(v) = prefs.edit().putBoolean("polish_bullets", v).apply()

    /** Podeli doteran tekst na pasuse, prazan red izmedju. */
    var polishParagraphs: Boolean
        get() = prefs.getBoolean("polish_paragraphs", true)
        set(v) = prefs.edit().putBoolean("polish_paragraphs", v).apply()

    /** Poziva modelu danas — Google ne nudi nacin da se vidi preostala kvota. */
    fun countPolish() {
        val danas = java.time.LocalDate.now().toString()
        val e = prefs.edit()
        if (prefs.getString("polish_day", "") != danas) {
            e.putString("polish_day", danas).putInt("polish_count", 0)
        }
        e.putInt("polish_count", polishCountToday + 1).apply()
    }

    val polishCountToday: Int
        get() = if (prefs.getString("polish_day", "") == java.time.LocalDate.now().toString())
            prefs.getInt("polish_count", 0) else 0

    var polishModel: String
        get() = prefs.getString("polish_model", "")!!
        set(v) = prefs.edit().putString("polish_model", v.trim()).apply()

    /** Model samo za kasniju obradu teksta; ne menja model transkripcije. */
    var textModel: String
        get() = if (prefs.getString("text_model", "gemini") == "groq") "groq" else "gemini"
        set(v) = prefs.edit().putString("text_model", if (v == "groq") "groq" else "gemini").apply()

    // --- Potrosnja podataka ---

    val bytesSent: Long get() = prefs.getLong("bytes_sent", 0)
    val bytesReceived: Long get() = prefs.getLong("bytes_received", 0)
    val dictationCount: Int get() = prefs.getInt("dictation_count", 0)
    val secondsSpoken: Long get() = prefs.getLong("seconds_spoken", 0)
    val recordedSeconds: Long get() = prefs.getLong("recorded_millis", 0) / 1000

    fun addRecordedSeconds(seconds: Double) {
        if (seconds <= 0) return
        prefs.edit().putLong(
            "recorded_millis",
            prefs.getLong("recorded_millis", 0) + (seconds * 1000).roundToLong(),
        ).apply()
    }

    fun addTraffic(
        sent: Long,
        received: Long,
        seconds: Double,
        countDictation: Boolean = true,
    ) {
        prefs.edit()
            .putLong("bytes_sent", bytesSent + sent)
            .putLong("bytes_received", bytesReceived + received)
            // Naknadna obrada teksta troši podatke, ali nije novi diktat.
            .putInt("dictation_count", dictationCount + if (countDictation) 1 else 0)
            .putLong("seconds_spoken", secondsSpoken + seconds.toLong())
            .apply()
    }

    fun resetTraffic() {
        prefs.edit()
            .remove("bytes_sent").remove("bytes_received")
            .remove("dictation_count").remove("seconds_spoken")
            .remove("recorded_millis")
            .apply()
    }

    val sampleRate = 16_000
    val maxSeconds = 30          // obican rezim: koliko traje jedan snimak
    val maxRequestSeconds = 30   // najduzi pojedinacni zahtev ka servisu
    val redAfterSeconds = 15     // od ove sekunde tajmer pocrveni
}
