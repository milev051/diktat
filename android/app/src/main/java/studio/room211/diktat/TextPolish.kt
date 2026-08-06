package studio.room211.diktat

/**
 * Doterivanje prepoznatog teksta — isto sto radi i macOS verzija.
 */
object TextPolish {

    /**
     * Tacka, zarez i dvotacka se brisu samo kad NISU izmedju cifara: endpoint
     * ih vraca kao decimalni separator ("3,5") i kao satnicu ("10:00"), pa bi
     * ih slepo brisanje spojilo u 35 i 1000. Crtica se brise samo kad stoji
     * sama, da "crno-beli" ostane celo.
     */
    private val PUNCT = Regex(
        // Znaci su pisani kao \uXXXX namerno: krivi navodnici i crte se lako
        // izgube pri kopiranju izmedju alata, a onda pravilo tiho oslabi.
        """(?<!\d)[.,:]""" +                                 // tacka/zarez/dvotacka bez cifre ispred
            """|[.,:](?!\d)""" +                             // ili bez cifre iza
            """|[!?;\u2026\u00AB\u00BB\u201E\u201C\u201D"()\[\]{}]""" +
            """|(?<=\s)[-\u2013\u2014](?=\s)"""
    )

    private val DIACRITICS = mapOf(
        'č' to "c", 'ć' to "c", 'ž' to "z", 'š' to "s", 'đ' to "dj",
        'Č' to "C", 'Ć' to "C", 'Ž' to "Z", 'Š' to "S", 'Đ' to "Dj",
    )

    /**
     * Tacka je separator hiljada samo ako je prate TACNO tri cifre i tu se broj
     * zavrsava: "5.000" -> "5000", ali "verzija 2.0" i "android 4.4" ostaju celi.
     * Zarez se ne dira — on je decimalni.
     */
    private val THOUSANDS = Regex("""(?<=\d)\.(?=\d{3}(?!\d))""")

    fun joinThousands(text: String): String {
        var out = text
        var previous: String
        do {                       // "1.500.000" ima vise tacaka
            previous = out
            out = THOUSANDS.replace(out, "")
        } while (out != previous)
        return out
    }

    fun stripPunctuation(text: String): String =
        PUNCT.replace(text, "").split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")

    /** č ć ž š đ -> c c z s dj. Opciono; podrazumevano iskljuceno. */
    fun toAscii(text: String): String = buildString {
        for (ch in text) append(DIACRITICS[ch] ?: ch)
    }

    /**
     * Ista pravila, ali podela na pasuse prezivljava.
     *
     * `stripPunctuation` skuplja sve razmake u jedan, pa bi nad celim tekstom
     * pojeo prazne redove koje je model namerno stavio.
     */
    fun applyBlocks(raw: String, cfg: Config): String =
        raw.split(Regex("""\n\s*\n"""))
            .filter { it.isNotBlank() }
            .joinToString("\n\n") { apply(it, cfg, trailing = false).trim() }

    /**
     * Zavrsna obrada nad tekstom koji je model vec sredio.
     *
     * Tekst mu ide nedirnut, pa bi ova podesavanja inace potpuno izostala —
     * korisnik to vidi kao "skracenice su prestale da rade". Mala slova i
     * brisanje interpunkcije se ovde NE primenjuju: to je bas ono sto je model
     * dobio zadatak da uradi, pa bi jedno gasilo drugo.
     */
    fun afterModel(text: String, cfg: Config): String {
        if (text.isBlank()) return text
        var out = text
        if (cfg.joinThousands) out = joinThousands(out)
        if (cfg.abbreviations) {
            out = Abbreviations.apply(out, Abbreviations.parse(cfg.abbreviationRules))
        }
        if (cfg.asciiDiacritics) out = toAscii(out)
        return out
    }

    fun apply(raw: String, cfg: Config, trailing: Boolean = true): String {
        var text = raw.trim()
        if (text.isEmpty()) return text
        // „Kako sam izgovorio" znaci mala slova i bez interpunkcije; „sirovo"
        // ostavlja ono sto Google vrati; „sredjeno" je posao modela, pa se ovde
        // ne dira.
        if (cfg.joinThousands) text = joinThousands(text)
        if (cfg.stripPunctuation) text = stripPunctuation(text)
        if (cfg.lowercase) text = text.lowercase()
        if (cfg.abbreviations) {
            text = Abbreviations.apply(text, Abbreviations.parse(cfg.abbreviationRules))
        }
        if (cfg.asciiDiacritics) text = toAscii(text)
        if (trailing && cfg.trailingSpace) text = "$text "
        return text
    }
}
