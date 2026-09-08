package studio.room211.diktat

/**
 * Koliko sme da traje JEDAN pritisak, po izvoru transkripcije.
 *
 * Odvojeno od `Config` zato sto je taj vezan za `Context`, koji je u JVM
 * testovima prazan kalup i vraca podrazumevane vrednosti — pa bi test nad njim
 * tiho prolazio na praznom. Isto pravilo kao `_limit_seconds` u dictate/app.py;
 * menja se na oba mesta.
 */
object Granica {

    /**
     * Live je jedini izvor koji salje zvuk DOK snimas (~2,5 MB po minutu), pa
     * zaboravljen diktat tu curi podatke sve vreme, a ne tek na kraju. Kod
     * ostalih izvora zaboravljen diktat kosta samo vreme.
     */
    const val GEMINI_LIVE_PODRAZUMEVANO = 120

    fun sekundi(
        provider: String,
        dugoSnimanje: Boolean,
        geminiLive: Int,
        openAi: Int,
        neprekidno: Int,
        kratko: Int,
    ): Int = when {
        // Granica za Live vazi bez obzira na „dugo snimanje": ona ne stiti od
        // predugackog ZAHTEVA nego od zaboravljenog mikrofona koji trosi podatke.
        provider == "gemini_live" -> geminiLive
        !dugoSnimanje -> kratko
        provider == "openai" -> openAi
        else -> neprekidno
    }
}
