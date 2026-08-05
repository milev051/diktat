package studio.room211.diktat

/**
 * Doterivanje prepoznatog teksta — isto sto radi i macOS verzija.
 */
object TextPolish {

    /**
     * Tacka i zarez se brisu samo kad NISU izmedju cifara: endpoint ih vraca
     * kao decimalni separator ("3,5", "20,5 RSD"), pa bi ih slepo brisanje
     * spojilo u 35. Crtica se brise samo kad stoji sama, da "crno-beli"
     * ostane celo.
     */
    private val PUNCT = Regex(
        // Znaci su pisani kao \uXXXX namerno: krivi navodnici i crte se lako
        // izgube pri kopiranju izmedju alata, a onda pravilo tiho oslabi.
        """(?<!\d)[.,]""" +                                  // tacka/zarez bez cifre ispred
            """|[.,](?!\d)""" +                              // ili bez cifre iza
            """|[!?;:\u2026\u00AB\u00BB\u201E\u201C\u201D"()\[\]{}]""" +
            """|(?<=\s)[-\u2013\u2014](?=\s)"""
    )

    private val DIACRITICS = mapOf(
        'č' to "c", 'ć' to "c", 'ž' to "z", 'š' to "s", 'đ' to "dj",
        'Č' to "C", 'Ć' to "C", 'Ž' to "Z", 'Š' to "S", 'Đ' to "Dj",
    )

    fun stripPunctuation(text: String): String =
        PUNCT.replace(text, "").split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")

    /** č ć ž š đ -> c c z s dj. Opciono; podrazumevano iskljuceno. */
    fun toAscii(text: String): String = buildString {
        for (ch in text) append(DIACRITICS[ch] ?: ch)
    }

    fun apply(raw: String, cfg: Config): String {
        var text = raw.trim()
        if (text.isEmpty()) return text
        if (cfg.stripPunctuation) text = stripPunctuation(text)
        if (cfg.lowercase) text = text.lowercase()
        if (cfg.abbreviations) {
            text = Abbreviations.apply(text, Abbreviations.parse(cfg.abbreviationRules))
        }
        if (cfg.asciiDiacritics) text = toAscii(text)
        if (cfg.trailingSpace) text = "$text "
        return text
    }
}
