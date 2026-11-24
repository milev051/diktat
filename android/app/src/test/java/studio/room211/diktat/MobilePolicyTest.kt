package studio.room211.diktat

import org.junit.Assert.*
import org.junit.Test

class MobilePolicyTest {
    @Test fun `new and obsolete providers select Gemini while Google remains available`() {
        for (old in listOf(null, "openai", "gemini", "", "gemini_live"))
            assertEquals("gemini_live", MobilePolicy.provider(old))
        assertEquals("google", MobilePolicy.provider("google"))
        assertEquals("soniox", MobilePolicy.provider("soniox"))
        assertEquals(setOf("google", "gemini_live", "soniox"), MobilePolicy.providers)
    }
    @Test fun `both supported providers get ten minutes in the recording service`() {
        for (provider in MobilePolicy.providers) {
            assertEquals(600, Granica.sekundi(provider, true, MobilePolicy.MAX_SECONDS,
                3600, MobilePolicy.MAX_SECONDS, 30))
        }
    }
    @Test fun `soniox tokens drop control markers`() {
        val tokeni = listOf("Dobar", " dan", "<end>").map { org.json.JSONObject().put("text", it) }
        assertEquals("Dobar dan", SonioxStt.tekst(tokeni))
    }
}
