package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class GroqTest {
    private fun le32(bytes: ByteArray, at: Int) =
        ByteBuffer.wrap(bytes, at, 4).order(ByteOrder.LITTLE_ENDIAN).int

    @Test
    fun `wav zaglavlje opisuje ceo zvuk`() {
        val pcm = ByteArray(200) { (it % 256).toByte() }
        val wav = Groq.wav(pcm, 16_000)
        assertEquals("RIFF", String(wav, 0, 4))
        assertEquals("WAVE", String(wav, 8, 4))
        assertEquals(16_000, le32(wav, 24))
        assertEquals(pcm.size, le32(wav, 40))
        assertEquals(pcm.size + 44, wav.size)
    }

    @Test
    fun `podrazumevani modeli su postavljeni`() {
        assertTrue(Groq.DEFAULT_TRANSCRIPTION_MODEL.isNotBlank())
        assertEquals("openai/gpt-oss-120b", Groq.DEFAULT_MERGE_MODEL)
    }
}
