package studio.room211.diktat

/** Kada node.text sme da se koristi kao postojeći korisnikov tekst. */
internal object InputContent {
    /** Ne gradi se ceo tekst polja od accessibility natpisa ili selekcije. */
    fun setTextFallback(current: String, showingHint: Boolean, spoken: String): String? =
        if (current.isEmpty() || showingHint) spoken else null

    fun canAppend(text: String, hint: String?, start: Int, end: Int): Boolean {
        // Jednak natpis može biti i korisnikova reč: PASTE čuva oba slučaja.
        if (text.isEmpty() || text == hint) return false
        // WebView prijavljuje (0, 0) i uz placeholder bez hint metapodataka.
        // Ne proveravamo same reči poput „Poruka”: korisnik sme da ih diktira.
        return start in 0..text.length && end in 0..text.length && maxOf(start, end) > 0
    }
}
