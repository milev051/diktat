package studio.room211.diktat

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KasnjenjeTest {
    private fun pusti(k: Kasnjenje, od: Long, doMs: Long) {
        var t = od
        while (t < doMs) { k.glasKomad(t, 100); t += 100 }
    }

    @Test fun sumPosleDugeTisineNijeKasnjenje() {
        val k = Kasnjenje()
        pusti(k, 10_000, 10_200)
        assertFalse(k.kasni(10_300))
        assertFalse(k.kasni(20_000))
    }

    @Test fun govorBezTekstaJeKasnjenje() {
        val k = Kasnjenje()
        pusti(k, 0, 5_000)
        assertTrue(k.kasni(5_000))
    }

    @Test fun tisinaPosleGovoraGasiZuto() {
        val k = Kasnjenje()
        pusti(k, 0, 5_000)
        assertFalse(k.kasni(7_000))
    }

    @Test fun tekstResetuje() {
        val k = Kasnjenje()
        pusti(k, 0, 5_000)
        k.reset()
        pusti(k, 5_000, 6_000)
        assertFalse(k.kasni(6_000))
    }
}
