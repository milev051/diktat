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
     * Samo skracenice, nad tekstom koji je model vec sredio.
     *
     * U formalnom rezimu tekst ide modelu nedirnut, pa bi skracenice inace
     * potpuno izostale — korisnik ih vidi kao "prestale su da rade".
     */
    fun abbreviationsOnly(text: String, cfg: Config): String =
        if (!cfg.abbreviations || text.isBlank()) text
        else Abbreviations.apply(text, Abbreviations.parse(cfg.abbreviationRules))

    fun apply(raw: String, cfg: Config, trailing: Boolean = true): String {
        var text = raw.trim()
        if (text.isEmpty()) return text
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
