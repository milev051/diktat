package studio.room211.diktat

/**
 * Skracivanje cestih fraza i uredjivanje jedinica uz brojeve.
 *
 * Pravilo je `fraza=skracenica`. Slepljene jedinice se razdvajaju. Brojevi
 * napisani recima ostaju onako kako ih je transkripcija vratila.
 *
 * Duze fraze idu prve, inace bi pravilo za "znam" pojelo "ne znam" pre nego
 * sto ono dodje na red. Poklapaju se samo cele reci — "znamenito" i "poznam"
 * ostaju netaknuti.
 *
 * Red koji pocinje sa `~` je regularni izraz, a `{1}`..`{9}` u zameni su
 * uhvacene grupe.
 *
 * Isti spisak sluzi i kao ispravljac: ako prepoznavanje stalno gresi istu rec,
 * dodaj `pogresno=ispravno` i tu.
 */
object Abbreviations {

    /** Jedno pravilo po redu, oblik `fraza=skracenica`. */
    val DEFAULT = listOf(
        "ne znam" to "nzm",
        "jebi ga" to "jbg",
        "jebem li ga" to "jbm li ga",
        "je li" to "je l",
        "jeli" to "je l",
        "znam" to "znm",
        "ne mogu" to "nmg",
        "nema veze" to "nmvz",
        "na primer" to "npr",
        "i tako dalje" to "itd",
        "to jest" to "tj",
        "to je to" to "tjt",
        "svejedno" to "svj",
        // Prepoznavanje ovo vraca i rastavljeno, pa oba oblika moraju u spisak.
        "sve jedno" to "svj",
        "mislim" to "msm",
    )

    fun defaultText(): String =
        DEFAULT.joinToString("\n") { (fraza, kratko) -> "$fraza=$kratko" }

    /**
     * Poslednji red pobedjuje ako je ista fraza navedena vise puta — inace bi
     * stari red iznad novog tiho pojeo rec pre nego sto novi dodje na red.
     */
    fun parse(text: String): List<Pair<String, String>> {
        val seen = LinkedHashMap<String, String>()
        for ((phrase, replacement) in rawParse(text)) seen[phrase.lowercase()] = replacement
        return seen.entries.map { it.key to it.value }
    }

    private fun rawParse(text: String): List<Pair<String, String>> =
        text.lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") && it.contains("=") }
            .map { line ->
                val i = line.indexOf('=')
                line.substring(0, i).trim() to line.substring(i + 1).trim()
            }
            .filter { it.first.isNotEmpty() }
            .toList()

    /** `{1}` u zameni je grupa; sve ostalo je doslovno. */
    private val GROUP = Regex("""\{(\d)\}""")

    private val NUMBER_VALUES = mapOf(
        "nula" to 0L,
        "jedan" to 1L, "jedna" to 1L, "jedno" to 1L,
        "dva" to 2L, "dve" to 2L, "dvije" to 2L,
        "tri" to 3L, "četiri" to 4L, "cetiri" to 4L, "pet" to 5L,
        "šest" to 6L, "sest" to 6L, "sedam" to 7L, "osam" to 8L, "devet" to 9L,
        "deset" to 10L, "jedanaest" to 11L, "dvanaest" to 12L,
        "trinaest" to 13L, "četrnaest" to 14L, "cetrnaest" to 14L,
        "petnaest" to 15L, "šesnaest" to 16L, "sesnaest" to 16L,
        "sedamnaest" to 17L, "osamnaest" to 18L, "devetnaest" to 19L,
        "dvadeset" to 20L, "trideset" to 30L, "četrdeset" to 40L,
        "cetrdeset" to 40L, "pedeset" to 50L, "šezdeset" to 60L,
        "sezdeset" to 60L, "sedamdeset" to 70L, "osamdeset" to 80L,
        "devedeset" to 90L, "sto" to 100L, "stotinu" to 100L,
        "dvesta" to 200L, "trista" to 300L, "četiristo" to 400L,
        "cetiristo" to 400L, "petsto" to 500L, "šeststo" to 600L,
        "seststo" to 600L, "sedamsto" to 700L, "osamsto" to 800L,
        "devetsto" to 900L,
    )

    private val SCALES = mapOf(
        "hiljadu" to 1_000L, "hiljada" to 1_000L, "hiljade" to 1_000L,
        "milion" to 1_000_000L, "miliona" to 1_000_000L,
        "milijardu" to 1_000_000_000L, "milijarde" to 1_000_000_000L,
    )

    private val NUMBER_WORDS = (NUMBER_VALUES.keys + SCALES.keys)
        .sortedByDescending { it.length }
    private val NUMBER_PART = NUMBER_WORDS.joinToString("|") { Regex.escape(it) }
    private val UNITS = listOf(
        "minuta", "minut", "minute", "min", "sati", "sata", "sat",
        "časova", "časa", "čas", "sekundi", "sekunde", "sekunda", "sek",
        "dinara", "dinar", "din", "kilometara", "kilometar", "km",
        "metara", "metar", "m", "grama", "gram", "kg", "evra", "evro",
        "eur", "dolara", "dolar", "usd", "procenata", "procenat", "h", "s",
    )
    private val UNIT_PART = UNITS.sortedByDescending { it.length }
        .joinToString("|") { Regex.escape(it) }
    // Uz broj napisan RECIMA jedinica mora imati bar dva slova. Inace se obicne
    // reci raspadaju: „jednom" je „jedno" + „m", pa je postajalo „jedno m".
    // Isto „stos" („sto" + „s"), „stom" i „trim". Govor nikad ne daje „petm" ni
    // „trih" — prepoznavanje napise „pet metara" ili „5 m" — pa se ovim ne gubi
    // nista, a 171 lazno poklapanje nestane. Isto i u dictate/abbrev.py.
    private val LONG_UNIT_PART = UNITS.filter { it.length > 1 }
        .sortedByDescending { it.length }
        .joinToString("|") { Regex.escape(it) }
    private val GLUED_UNIT = Regex(
        """(?<!\p{L})($NUMBER_PART)($LONG_UNIT_PART)(?!\p{L})""",
        RegexOption.IGNORE_CASE,
    )
    private val GLUED_DIGIT = Regex(
        """(?<!\p{L})(\d+(?:[.,]\d+)?)(\s*)($UNIT_PART)(?!\p{L})""",
        RegexOption.IGNORE_CASE,
    )
    // Uz cifru se lepi SAMO kratka oznaka ("15min", "20km", "10kg"), nikad cela
    // rec: "100dolara" i "500dinara" izgledaju kao greska, a bas to je radila
    // ranija verzija — `normalizeSpokenNumbers` bi ih razdvojila, pa bi ih ovaj
    // prolaz odmah zalepio nazad. Trocifrene oznake valuta ostaju sa razmakom,
    // isto kao "5000 RSD" iz korisnickog pravila bez „<". Isto i u abbrev.py.
    private val SYMBOLS = listOf("min", "sek", "din", "km", "kg", "m", "h", "s")
    private val SYMBOL_PART = SYMBOLS.sortedByDescending { it.length }
        .joinToString("|") { Regex.escape(it) }
    private val DIGIT_WITH_UNIT = Regex(
        """(?<!\p{L})(\d+(?:[.,]\d+)?)[ \t]+($SYMBOL_PART)(?!\p{L})""",
        RegexOption.IGNORE_CASE,
    )
    private val MINUTE_WITH_DIGITS = Regex(
        """(?<!\p{L})(\d+(?:[.,]\d+)?)[ \t]+(minuta|minut|minute|min)(?!\p{L})""",
        RegexOption.IGNORE_CASE,
    )
    private val MINUTE_WORD = Regex(
        """(?<!\p{L})(minuta|minut|minute)(?!\p{L})""",
        RegexOption.IGNORE_CASE,
    )
    private val STO_KAO_STO = Regex(
        """(?i)(?<!\p{L})sto(?=\s+(?:je|sam|si|smo|ste|su|će|ce|ću|cu|bi|bih|bismo|biste|nisam|nije|nisi|nismo|niste|nisu|može|moze|mogu|treba|trebalo)(?!\p{L}))""",
    )
    private val STO_U_KONTEKSTU = Regex(
        """(?i)(?<!\p{L})(zato)\s+sto(?!\p{L})""",
    )
    /** Razdvoji tekstualni broj od jedinice, a cifru spoji sa jedinicom. */
    fun normalizeSpokenNumbers(text: String): String {
        if (text.isEmpty()) return text
        // ASR ponekad vrati „sto“ umesto „što“. Zaštiti veznički obrazac.
        var out = STO_U_KONTEKSTU.replace(text) { match ->
            "${match.groupValues[1]} što"
        }
        out = STO_KAO_STO.replace(out, "što")
        out = GLUED_UNIT.replace(out) { match ->
            match.groupValues[1] + " " + match.groupValues[2]
        }
        out = GLUED_DIGIT.replace(out) { match ->
            match.groupValues[1] + " " + match.groupValues[3]
        }
        out = MINUTE_WITH_DIGITS.replace(out) { match ->
            match.groupValues[1] + "min"
        }
        out = MINUTE_WORD.replace(out, "min")
        return out
    }

    private fun toJavaReplacement(user: String): String {
        val out = StringBuilder()
        var last = 0
        for (m in GROUP.findAll(user)) {
            out.append(Regex.escapeReplacement(user.substring(last, m.range.first)))
            out.append("$").append(m.groupValues[1])
            last = m.range.last + 1
        }
        out.append(Regex.escapeReplacement(user.substring(last)))
        return out.toString()
    }

    fun apply(
        text: String,
        rules: List<Pair<String, String>>,
    ): String {
        if (text.isBlank()) return text
        var out = normalizeSpokenNumbers(text)
        if (rules.isEmpty()) return DIGIT_WITH_UNIT.replace(out) { match ->
            match.groupValues[1] + match.groupValues[2]
        }

        // Ako build ubaci regex pravilo, ono ide pre prostih zamena da se
        // složenija zamena ne pokvari ranijim poklapanjem.
        for ((pattern, replacement) in rules.filter { it.first.startsWith("~") }) {
            runCatching {
                out = Regex(pattern.substring(1), RegexOption.IGNORE_CASE)
                    .replace(out, toJavaReplacement(replacement))
            }
        }

        for ((phrase, replacement) in rules
            .filter { !it.first.startsWith("~") }
            .sortedByDescending { it.first.length }) {
            val join = replacement.startsWith("<")
            // trim posle skidanja "<": napisano kao "< RSD" razmak bi inace
            // dosao iz same zamene, pa bi izgledalo da "<" ne radi.
            val short = if (join) replacement.substring(1).trim() else replacement

            // Lookbehind ide POSLE \s*, ne pre: cifra ispred ("15 minuta") je
            // rec-znak, pa bi provera stavljena ranije oborila poklapanje.
            val pattern = Regex(
                (if (join) """\s*""" else "") +
                    """(?<!\p{L})${Regex.escape(phrase)}(?!\p{L})""",
                RegexOption.IGNORE_CASE,
            )
            out = pattern.replace(out, Regex.escapeReplacement(short))
        }
        // Ovo ide POSLE korisničkih pravila: `dinara=RSD` treba da zadrži
        // razmak, dok `dinara=<RSD` namerno lepi zamenu uz cifru.
        return DIGIT_WITH_UNIT.replace(out) { match ->
            match.groupValues[1] + match.groupValues[2]
        }
    }
}
