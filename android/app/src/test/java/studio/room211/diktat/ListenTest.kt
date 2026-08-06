package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Zaglavlje snimka koji ide modelu. */
class ListenTest {

    private fun le32(bytes: ByteArray, at: Int) =
        ByteBuffer.wrap(bytes, at, 4).order(ByteOrder.LITTLE_ENDIAN).int

    @Test
    fun `wav zaglavlje opisuje bas ovaj zvuk`() {
        val pcm = ByteArray(200) { (it % 256).toByte() }
        val wav = Listen.wav(pcm, 16_000)
        assertEquals("RIFF", String(wav, 0, 4))
        assertEquals("WAVE", String(wav, 8, 4))
        assertEquals(16_000, le32(wav, 24))
        // Pogresna velicina bi modelu dala odsecen zvuk.
        assertEquals(pcm.size, le32(wav, 40))
        assertEquals(pcm.size + 44, wav.size)
    }

    @Test
    fun `pcm ostaje netaknut iza zaglavlja`() {
        val pcm = byteArrayOf(1, 2, 3, 4, 5, 6)
        val wav = Listen.wav(pcm, 16_000)
        assertEquals(pcm.toList(), wav.drop(44))
    }
}
