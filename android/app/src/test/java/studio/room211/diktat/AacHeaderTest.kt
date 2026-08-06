package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** ADTS zaglavlje se pise rukom, pa mora da bude provereno. */
class AacHeaderTest {

    private fun bits(b: Byte) = b.toInt() and 0xFF

    @Test
    fun `sinhro rec i osnovna polja`() {
        val h = AacEncoder.adts(100, AacEncoder.RATES.getValue(16_000))
        assertEquals(7, h.size)
        assertEquals(0xFF, bits(h[0]))
        // MPEG-4, Layer 0, bez CRC
        assertEquals(0xF1, bits(h[1]))
        // AAC LC (profil 2 -> 01) i indeks ucestanosti 8 za 16 kHz
        assertEquals(0b01_1000_00, bits(h[2]))
    }

    @Test
    fun `duzina okvira ukljucuje zaglavlje`() {
        val duzina = 100
        val h = AacEncoder.adts(duzina, 8)
        val upisano = ((bits(h[3]) and 0x03) shl 11) or (bits(h[4]) shl 3) or (bits(h[5]) shr 5)
        assertEquals(duzina + 7, upisano)
    }

    @Test
    fun `veliki okvir ne prelije polje`() {
        val duzina = 4000
        val h = AacEncoder.adts(duzina, 8)
        val upisano = ((bits(h[3]) and 0x03) shl 11) or (bits(h[4]) shl 3) or (bits(h[5]) shr 5)
        assertEquals(duzina + 7, upisano)
    }

    @Test
    fun `poznate ucestanosti imaju indeks`() {
        assertEquals(8, AacEncoder.RATES.getValue(16_000))
        assertTrue(48_000 in AacEncoder.RATES)
    }
}
