package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class OpenAiTranscriptionTest {

    private fun le32(bytes: ByteArray, at: Int) =
        ByteBuffer.wrap(bytes, at, 4).order(ByteOrder.LITTLE_ENDIAN).int

    @Test
    fun `koristi trazeni model i endpoint`() {
        assertEquals("gpt-transcribe", OpenAiTranscription.MODEL)
        assertTrue(OpenAiTranscription.ENDPOINT.endsWith("/v1/audio/transcriptions"))
    }

    @Test
    fun `prompt bira pismo`() {
        assertTrue(OpenAiTranscription.prompt("auto").contains("srpskom jeziku"))
        assertTrue(OpenAiTranscription.prompt("cyrillic").contains("ćirilicom"))
        assertTrue(OpenAiTranscription.prompt("latin").contains("latinicom"))
    }

    @Test
    fun `cirilica u latinicu cuva strukturu teksta`() {
        val input = "Љубав и џез — 12.500 dinara.\nhttps://primer.rs OpenAI"
        assertEquals(
            "Ljubav i džez — 12.500 dinara.\nhttps://primer.rs OpenAI",
            OpenAiTranscription.toLatin(input),
        )
        assertEquals(
            "Lj Nj Đ Dž Ć Č Ž Š J lj nj đ dž ć č ž š j",
            OpenAiTranscription.toLatin("Љ Њ Ђ Џ Ћ Ч Ж Ш Ј љ њ ђ џ ћ ч ж ш ј"),
        )
    }

    @Test
    fun `wav zaglavlje opisuje ceo snimak`() {
        val pcm = ByteArray(200) { (it % 256).toByte() }
        val wav = OpenAiTranscription.wav(pcm, 16_000)
        assertEquals("RIFF", String(wav, 0, 4))
        assertEquals("WAVE", String(wav, 8, 4))
        assertEquals(16_000, le32(wav, 24))
        assertEquals(pcm.size, le32(wav, 40))
        assertEquals(pcm.size + 44, wav.size)
    }
}
