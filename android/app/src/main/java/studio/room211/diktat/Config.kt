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

    var trailingSpace: Boolean
        get() = prefs.getBoolean("trailing_space", true)
        set(v) = prefs.edit().putBoolean("trailing_space", v).apply()

    val sampleRate = 16_000
    val maxSeconds = 30          // endpoint odbija duze zahteve
    val redAfterSeconds = 15     // od ove sekunde tajmer pocrveni
}
