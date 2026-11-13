package studio.room211.diktat

import org.junit.Assert.*
import org.junit.Test

class MobilePolicyTest {
    @Test fun `new and obsolete providers select Gemini while Google remains available`() {
        for (old in listOf(null, "openai", "gemini", "", "gemini_live"))
            assertEquals("gemini_live", MobilePolicy.provider(old))
        assertEquals("google", MobilePolicy.provider("google"))
        assertEquals(setOf("google", "gemini_live"), MobilePolicy.providers)
    }
    @Test fun `both supported providers get ten minutes in the recording service`() {
        for (provider in MobilePolicy.providers) {
            assertEquals(600, Granica.sekundi(provider, true, MobilePolicy.MAX_SECONDS,
                3600, MobilePolicy.MAX_SECONDS, 30))
        }
    }
}
