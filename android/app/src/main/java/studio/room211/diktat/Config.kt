package studio.room211.diktat

import android.content.Context

/** Podesavanja, ista imena i podrazumevane vrednosti kao u macOS verziji. */
class Config(context: Context) {

    private val prefs = context.getSharedPreferences("diktat", Context.MODE_PRIVATE)

    var language: String
        get() = prefs.getString("language", "sr-RS")!!
        set(v) = prefs.edit().putString("language", v).apply()

    var apiKey: String
        get() = prefs.getString("api_key", "")!!
        set(v) = prefs.edit().putString("api_key", v).apply()

    /** Deo izbora `textStyle`, ne zaseban prekidac. */
    val lowercase: Boolean
        get() = textStyle == "spoken"

    /** Deo izbora `textStyle`, ne zaseban prekidac. */
    val stripPunctuation: Boolean
        get() = textStyle == "spoken"

    var profanityFilter: Boolean
        get() = prefs.getBoolean("profanity_filter", false)
        set(v) = prefs.edit().putBoolean("profanity_filter", v).apply()

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

    /** Salji FLAC umesto sirovog PCM-a: oko 40% manje podataka. */
    var compressAudio: Boolean
        get() = prefs.getBoolean("compress_audio", true)
        set(v) = prefs.edit().putBoolean("compress_audio", v).apply()

    /** "5.000" -> "5000"; zarez kao decimalni ostaje. */
    /** Uvek ukljuceno: „5.000" -> „5000"; zarez ostaje decimalni. */
    val joinThousands = true

    var abbreviations: Boolean
        get() = prefs.getBoolean("abbreviations", true)
        set(v) = prefs.edit().putBoolean("abbreviations", v).apply()

    /**
     * Pravila, jedno po redu, oblik `fraza=skracenica`.
     *
     * Uz pravila se pamti i kako su podrazumevana izgledala kad su sacuvana.
     * Ako se to dvoje poklapa, korisnik ih nije menjao — pa nova verzija sme
     * da donese nova podrazumevana sama. Ako se razlikuje, korisnikova pravila
     * se ne diraju.
     */
    var abbreviationRules: String
        get() {
            val saved = prefs.getString("abbreviation_rules", null)
                ?: return Abbreviations.defaultText()
            val snapshot = prefs.getString("abbreviation_defaults", null)
            val current = Abbreviations.defaultText()
            if (snapshot != null && saved == snapshot && snapshot != current) {
                abbreviationRules = current
                return current
            }
            return saved
        }
        set(v) = prefs.edit()
            .putString("abbreviation_rules", v)
            .putString("abbreviation_defaults", Abbreviations.defaultText())
            .apply()

    /** Ne snimaj ako nema polja u koje bi tekst usao. */
    var requireInputField: Boolean
        get() = prefs.getBoolean("require_input_field", true)
        set(v) = prefs.edit().putBoolean("require_input_field", v).apply()

    /** Posle uspesnog upisa vrati clipboard kakav je bio — da izdiktirano ne
     *  ostane u istoriji clipboard-a. */
    var restoreClipboard: Boolean
        get() = prefs.getBoolean("restore_clipboard", true)
        set(v) = prefs.edit().putBoolean("restore_clipboard", v).apply()

    /** Uvek ukljuceno: bez razmaka se recenice slepe pri nadovezivanju. */
    val trailingSpace = true

    // --- Formalni rezim ---
    // Kljuc ostaje pri nadogradnji aplikacije: SharedPreferences prezivljava
    // instalaciju preko postojece, dok je paket i potpis isti.
    var polish: Boolean
        get() = prefs.getBoolean("polish", false)
        set(v) = prefs.edit().putBoolean("polish", v).apply()

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
            // "raw" je uklonjen: niko ga nije koristio, a bio je treci ishod za
            // isto pitanje. Ko ga je imao, dobija podrazumevano ponasanje.
            prefs.getString("text_style", null)?.let { return if (it == "raw") "spoken" else it }
            val prevedeno = when {
                prefs.getBoolean("polish", false) && prefs.getBoolean("polish_tidy", true) ->
                    "written"
                prefs.getBoolean("lowercase", true) ||
                    prefs.getBoolean("strip_punctuation", true) -> "spoken"
                else -> "raw"
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
    var outputLanguage: String
        get() = prefs.getString("output_language", "") ?: ""
        set(v) = prefs.edit().putString("output_language", v).apply()

    /** Skracenice i nazivi koje endpoint stalno gresi; idu modelu uz snimak. */
    var vocabulary: String
        get() = prefs.getString("vocabulary", Listen.POJMOVI_PODRAZUMEVANO)
            ?: Listen.POJMOVI_PODRAZUMEVANO
        set(v) = prefs.edit().putString("vocabulary", v).apply()

    /** Koliko zvuka najvise cuvamo za grupnu proveru na kraju diktata. */
    val audioCheckMaxSeconds = 120

    /** Model slusa snimak i ispravlja prepis. */
    var audioCheck: Boolean
        get() = prefs.getBoolean("audio_check", false)
        set(v) = prefs.edit().putBoolean("audio_check", v).apply()

    /** Izbaci slucajno udvojene reci i fraze (govorna ispravka). */
    var polishDedupe: Boolean
        get() = prefs.getBoolean("polish_dedupe", false)
        set(v) = prefs.edit().putBoolean("polish_dedupe", v).apply()

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

    // --- Potrosnja podataka ---

    val bytesSent: Long get() = prefs.getLong("bytes_sent", 0)
    val bytesReceived: Long get() = prefs.getLong("bytes_received", 0)
    val dictationCount: Int get() = prefs.getInt("dictation_count", 0)
    val secondsSpoken: Long get() = prefs.getLong("seconds_spoken", 0)

    fun addTraffic(
        sent: Long,
        received: Long,
        seconds: Double,
        countDictation: Boolean = true,
    ) {
        prefs.edit()
            .putLong("bytes_sent", bytesSent + sent)
            .putLong("bytes_received", bytesReceived + received)
            // Provera snimka salje isti diktat drugi put — bajtovi se broje,
            // ali broj diktata ne sme da poraste.
            .putInt("dictation_count", dictationCount + if (countDictation) 1 else 0)
            .putLong("seconds_spoken", secondsSpoken + seconds.toLong())
            .apply()
    }

    fun resetTraffic() {
        prefs.edit()
            .remove("bytes_sent").remove("bytes_received")
            .remove("dictation_count").remove("seconds_spoken")
            .apply()
    }

    val sampleRate = 16_000
    val maxSeconds = 30          // obican rezim: koliko traje jedan snimak
    val maxRequestSeconds = 30   // najduzi pojedinacni zahtev ka servisu
    val redAfterSeconds = 15     // od ove sekunde tajmer pocrveni
}
