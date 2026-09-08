package studio.room211.diktat

/**
 * Odluka sta znaci „pravilno", odvojena od `SharedPreferences`.
 *
 * Odvojena zato sto je `Config` vezan za `Context`, koji je u JVM testovima
 * prazan kalup i vraca podrazumevane vrednosti — pa bi svaki test nad njim
 * tiho prolazio na praznom. Ovde je cista funkcija, ista kao `pravilno` i
 * `postavi_pravilno` u dictate/config.py; menja se na oba mesta.
 */
object Pravilno {

    /** Cetiri prekidaca; svaki UDALJAVA tekst od pravopisa. */
    data class Stanje(
        val malaSlova: Boolean,
        val bezInterpunkcije: Boolean,
        val bezKvacica: Boolean,
        val skracenice: Boolean,
    ) {
        /** „Pravilno" znaci: sva cetiri ugasena. */
        val pravilno: Boolean
            get() = !malaSlova && !bezInterpunkcije && !bezKvacica && !skracenice
    }

    val PODRAZUMEVANO = Stanje(
        malaSlova = true,
        bezInterpunkcije = true,
        bezKvacica = false,      // kvacice se podrazumevano ZADRZAVAJU
        skracenice = true,
    )

    val SVE_UGASENO = Stanje(false, false, false, false)

    /**
     * Sta postaviti kad se „pravilno" gasi.
     *
     * Vraca ono sto je bilo pre ukljucivanja, ne podrazumevano: `bezKvacica`
     * je podrazumevano iskljucen, pa bi povratak na podrazumevano tiho ukinuo
     * izbor onome ko ga drzi upaljenog. Bez zapamcenog stanja (rucno menjanje
     * pojedinacnih prekidaca) vraca se podrazumevano, da gasenje uvek nesto
     * uradi.
     */
    fun priGasenju(zapamceno: Stanje?): Stanje = zapamceno ?: PODRAZUMEVANO

    /**
     * Sta zapamtiti pri ukljucivanju.
     *
     * `null` znaci „ne diraj vec zapamceno": pamti se samo pri PRELASKU, jer
     * bi drugi poziv zapamtio vec ugasena stanja i povratak ne bi vratio nista.
     */
    fun priUkljucivanju(trenutno: Stanje): Stanje? =
        if (trenutno.pravilno) null else trenutno
}
