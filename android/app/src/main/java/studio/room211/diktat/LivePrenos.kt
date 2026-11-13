package studio.room211.diktat

/**
 * Tekst koji je korisnik već video ne sme da nestane ako tok pukne.
 *
 * `vidjeno` je poslednji ceo prepis. Pilula sme da pokaže samo rep.
 * `potvrdjeno` je ono što je već uspešno upisano u polje.
 */
class LivePrenos {
    private var vidjeno: String = ""
    private var potvrdjeno: String = ""

    @Synchronized
    fun vidi(tekst: String) {
        val t = tekst.trim()
        if (t.isNotEmpty()) vidjeno = t
    }

    @Synchronized
    fun vidjeno(): String = vidjeno

    @Synchronized
    fun potvrdi(deo: String) {
        val t = deo.trim()
        if (t.isEmpty()) return
        potvrdjeno = if (potvrdjeno.isEmpty()) t else "$potvrdjeno $t"
    }

    /** Šta još nije u polju. `konacan` je odgovor toka, prazan ako je pukao. */
    @Synchronized
    fun ostatak(konacan: String = ""): String =
        zaUpis(najbolji(vidjeno, konacan), potvrdjeno)

    companion object {
        fun najbolji(vidjeno: String, konacan: String): String {
            val v = vidjeno.trim()
            val k = konacan.trim()
            return when {
                k.isEmpty() -> v
                v.isEmpty() -> k
                k.startsWith(v) -> k
                v.startsWith(k) -> v
                k.length > v.length -> k
                else -> v
            }
        }

        /**
         * Vrati samo deo koji još nije upisan.
         * Ako se nizovi ne poklope, a u polju je već veći deo, ne dupliraj.
         */
        fun zaUpis(cilj: String, vec: String): String {
            val c = cilj.trim()
            val u = vec.trim()
            if (c.isEmpty()) return ""
            if (u.isEmpty()) return c
            if (c.startsWith(u)) return c.removePrefix(u).trim()
            val i = c.lastIndexOf(u)
            if (i >= 0) return c.substring(i + u.length).trim()
            if (u.length >= c.length / 2) return ""
            return c
        }
    }
}
