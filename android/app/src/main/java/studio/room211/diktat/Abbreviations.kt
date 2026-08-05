package studio.room211.diktat

/**
 * Skracivanje cestih fraza: "ne znam" -> "nzm", "jebi ga" -> "jbg".
 *
 * Pravilo je `fraza=skracenica`. Ako skracenica pocinje sa `<`, pojede se i
 * razmak ispred pa se zalepi za prethodnu rec: `minuta=<min` pretvara
 * "15 minuta" u "15min".
 *
 * Duze fraze idu prve, inace bi pravilo za "znam" pojelo "ne znam" pre nego
 * sto ono dodje na red. Poklapaju se samo cele reci — "znamenito" i "poznam"
 * ostaju netaknuti.
 *
 * Red koji pocinje sa `~` je regularni izraz, a `{1}`..`{9}` u zameni su
 * uhvacene grupe. Time se moze i premestati, sto valutama treba: dolar ide
 * ISPRED cifre, a dinar iza.
 *
 * Isti spisak sluzi i kao ispravljac: ako prepoznavanje stalno gresi istu rec,
 * dodaj `pogresno=ispravno` i tu.
 */
object Abbreviations {

    /** Jedno pravilo po redu, oblik `fraza=skracenica`. */
    val DEFAULT = listOf(
        "ne znam" to "nzm",
        "jebi ga" to "jbg",
        "znam" to "znm",
        "ne mogu" to "nmg",
        "nema veze" to "nmvz",
        "na primer" to "npr",
        "i tako dalje" to "itd",
        "to jest" to "tj",
        "to je to" to "tjt",
        "svejedno" to "svj",
        "mislim" to "msm",
        // "<" znaci: zalepi se za prethodnu rec
        "minuta" to "<min",
        "minut" to "<min",
        "procenata" to "<%",
        "posto" to "<%",
        // Dolar ide ispred cifre, pa treba premestanje — otud regularni izraz.
        """~(\d+(?:[.,]\d+)?)\s*dolara?""" to "\${1}",
        "dolara" to "$",
        "dolar" to "$",
        "dinara" to "<din",
        "dinar" to "<din",
        "evra" to "<€",
        "evro" to "<€",
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

    fun apply(text: String, rules: List<Pair<String, String>>): String {
        if (text.isBlank() || rules.isEmpty()) return text
        var out = text

        // Regularni izrazi idu prvi: "100 dolara" mora da postane "$100" pre
        // nego sto prosto pravilo stigne da pojede samu rec "dolara".
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
        return out
    }
}
