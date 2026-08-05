package studio.room211.diktat

/**
 * Skracivanje cestih fraza: "ne znam" -> "nzm", "jebi ga" -> "jbg".
 *
 * Duze fraze idu prve, inace bi pravilo za "znam" pojelo "ne znam" pre nego
 * sto ono dodje na red. Poklapaju se samo cele reci — "znamenito" i "poznam"
 * ostaju netaknuti.
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
        for ((phrase, short) in rules.sortedByDescending { it.first.length }) {
            val pattern = Regex(
                """(?<!\p{L})${Regex.escape(phrase)}(?!\p{L})""",
                RegexOption.IGNORE_CASE,
            )
            out = pattern.replace(out, Regex.escapeReplacement(short))
        }
        return out
    }
}
