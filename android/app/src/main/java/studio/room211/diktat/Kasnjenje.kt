package studio.room211.diktat

/**
 * Kada okvir uzivo pozuti: izgovoren zvuk ceka prepis (isto kao Mac
 * `dictate/kasnjenje.py`).
 *
 * Ranije pravilo (glas u poslednjoj 1 s, a teksta nema 4 s) palilo je zuto i
 * kad korisnik samo cuti: posle 4 s tisine dovoljan je jedan sum iznad praga.
 * Sada se broji koliko je glasa bilo od poslednjeg teksta.
 */
class Kasnjenje {
    private var glasMs = 0L
    private var prvi = -1L
    private var poslednji = -1L

    @Synchronized fun reset() {
        glasMs = 0L; prvi = -1L; poslednji = -1L
    }

    @Synchronized fun glasKomad(now: Long, trajanjeMs: Long) {
        if (trajanjeMs <= 0) return
        if (prvi < 0) prvi = now
        poslednji = now
        glasMs += trajanjeMs
    }

    @Synchronized fun kasni(now: Long): Boolean =
        prvi >= 0 && glasMs >= GLAS_MIN_MS && now - prvi >= CEKANJE_MS && now - poslednji < SVEZE_MS

    companion object {
        const val GLAS_MIN_MS = 1500L
        const val CEKANJE_MS = 4000L
        const val SVEZE_MS = 1500L
    }
}
