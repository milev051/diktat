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
        "nema veze" to "nvz",
        "molim te" to "mlm",
        "vidimo se" to "vs",
        "na primer" to "npr",
        "i tako dalje" to "itd",
        "u stvari" to "ustvari",
        // "<" znaci: zalepi se za prethodnu rec
        "minuta" to "<min",
        "minut" to "<min",
        "procenata" to "<%",
        "posto" to "<%",
    )

    fun defaultText(): String =
        DEFAULT.joinToString("\n") { (fraza, kratko) -> "$fraza=$kratko" }

    fun parse(text: String): List<Pair<String, String>> =
        text.lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") && it.contains("=") }
            .map { line ->
                val i = line.indexOf('=')
                line.substring(0, i).trim() to line.substring(i + 1).trim()
            }
            .filter { it.first.isNotEmpty() }
            .toList()

    fun apply(text: String, rules: List<Pair<String, String>>): String {
        if (text.isBlank() || rules.isEmpty()) return text
        var out = text
        for ((phrase, replacement) in rules.sortedByDescending { it.first.length }) {
            val join = replacement.startsWith("<")
            val short = if (join) replacement.substring(1) else replacement

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
