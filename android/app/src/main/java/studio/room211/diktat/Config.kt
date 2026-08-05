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

    var lowercase: Boolean
        get() = prefs.getBoolean("lowercase", true)
        set(v) = prefs.edit().putBoolean("lowercase", v).apply()

    var stripPunctuation: Boolean
        get() = prefs.getBoolean("strip_punctuation", true)
        set(v) = prefs.edit().putBoolean("strip_punctuation", v).apply()

    var profanityFilter: Boolean
        get() = prefs.getBoolean("profanity_filter", false)
        set(v) = prefs.edit().putBoolean("profanity_filter", v).apply()

    /** č ć ž š đ -> c c z s dj. Podrazumevano iskljuceno, kao na Mac-u. */
    var asciiDiacritics: Boolean
        get() = prefs.getBoolean("ascii_diacritics", false)
        set(v) = prefs.edit().putBoolean("ascii_diacritics", v).apply()

    var abbreviations: Boolean
        get() = prefs.getBoolean("abbreviations", true)
        set(v) = prefs.edit().putBoolean("abbreviations", v).apply()

    /** Pravila, jedno po redu, oblik `fraza=skracenica`. */
    var abbreviationRules: String
        get() = prefs.getString("abbreviation_rules", null) ?: Abbreviations.defaultText()
        set(v) = prefs.edit().putString("abbreviation_rules", v).apply()

    /** Ne snimaj ako nema polja u koje bi tekst usao. */
    var requireInputField: Boolean
        get() = prefs.getBoolean("require_input_field", true)
        set(v) = prefs.edit().putBoolean("require_input_field", v).apply()

    /** Posle uspesnog upisa vrati clipboard kakav je bio — da izdiktirano ne
     *  ostane u istoriji clipboard-a. */
    var restoreClipboard: Boolean
        get() = prefs.getBoolean("restore_clipboard", true)
        set(v) = prefs.edit().putBoolean("restore_clipboard", v).apply()

    var trailingSpace: Boolean
        get() = prefs.getBoolean("trailing_space", true)
        set(v) = prefs.edit().putBoolean("trailing_space", v).apply()

    val sampleRate = 16_000
    val maxSeconds = 30          // endpoint odbija duze zahteve
    val redAfterSeconds = 15     // od ove sekunde tajmer pocrveni
}
