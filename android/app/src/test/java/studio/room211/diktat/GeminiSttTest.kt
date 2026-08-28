package studio.room211.diktat

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Oblik setup poruke i citanje odgovora — bez mreze.
 *
 * Endpoint se ne moze pozvati u JVM testu, pa je ovo jedina odbrana od tihe
 * greske u imenu polja. Vrednosti su iste kao na Mac strani; ako se menjaju,
 * menjaju se na oba mesta.
 */
class GeminiSttTest {

    @Test
    fun modelIKonstante() {
        assertEquals("gemini-3.5-transcribe-live", GeminiStt.LIVE_MODEL)
        assertEquals(100, GeminiStt.LIVE_CHUNK_MS)
        assertEquals(2.0, GeminiStt.LIVE_TAIL_SILENCE, 0.001)
    }

    @Test
    fun kratakRokJeKraciOdPunog() {
        // Kratak vazi kad je celina finalizovana, pun kad je jos u letu.
        assertTrue(GeminiStt.LIVE_QUIET_MS < GeminiStt.LIVE_IDLE_MS)
    }

    @Test
    fun citaKonacanPrepis() {
        val poruka = JSONObject(
            """{"serverContent":{"inputTranscription":{"text":"zdravo"}}}"""
        )
        assertEquals("zdravo", GeminiStt.liveText(poruka))
        assertEquals("", GeminiStt.liveInterim(poruka))
    }

    @Test
    fun citaISnakeCase() {
        val poruka = JSONObject(
            """{"server_content":{"input_transcription":{"text":"zdravo"}}}"""
        )
        assertEquals("zdravo", GeminiStt.liveText(poruka))
    }

    @Test
    fun medjurezultatNijeKonacanPrepis() {
        val poruka = JSONObject(
            """{"serverContent":{"interimInputTranscription":{"text":"zdra"}}}"""
        )
        assertEquals("", GeminiStt.liveText(poruka))
        assertEquals("zdra", GeminiStt.liveInterim(poruka))
    }

    @Test
    fun praznaPoruka() {
        assertEquals("", GeminiStt.liveText(JSONObject("{}")))
        assertEquals("", GeminiStt.liveInterim(JSONObject("{}")))
    }

    /**
     * `generationComplete` stize posle SVAKE izgovorene celine, ne na kraju
     * diktata. Prekid na njemu je na Mac strani odbacivao sve posle prve pauze
     * — od 17s govora stizala je samo prva recenica. Zato ovde ne postoji
     * nikakva provera te zastavice: citanje se zavrsava tisinom.
     */
    @Test
    fun krajCelineNijeKrajDiktata() {
        val poruka = JSONObject("""{"serverContent":{"generationComplete":true}}""")
        assertEquals("", GeminiStt.liveText(poruka))
        assertEquals("", GeminiStt.liveInterim(poruka))
    }
}
