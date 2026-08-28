package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Test

class GroqTest {
    @Test
    fun `podrazumevani model za obradu teksta je postavljen`() {
        assertEquals("openai/gpt-oss-120b", Groq.DEFAULT_TEXT_MODEL)
    }
}
